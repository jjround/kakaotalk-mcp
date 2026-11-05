"""PC 카카오톡 창을 윈도우 메시지로 조작한다.

화면을 캡처하거나 마우스를 움직이지 않는다. 창 안의 입력칸·대화 목록 컨트롤을
핸들로 찾아 글자 넣기(WM_SETTEXT)와 키 신호(WM_KEYDOWN/UP)를 보낸다.
대화 읽기는 대화 목록에 Ctrl+A, Ctrl+C 신호를 보내 클립보드로 받은 뒤,
사용자의 원래 클립보드 텍스트를 되돌려 놓는다.

카카오톡 버전에 따라 컨트롤 클래스 이름이 다를 수 있어 환경 변수로 바꿀 수 있다.
`kakaotalk-mcp-diag`로 실제 클래스 이름을 확인할 것.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time

if sys.platform != "win32":
    raise ImportError("kakaotalk-mcp는 Windows의 PC 카카오톡에서만 동작합니다.")

import win32api
import win32clipboard
import win32con
import win32gui
import win32process

from .parse import messages_after, parse_messages

_user32 = ctypes.windll.user32  # pywin32에 없는 SetKeyboardState 등은 직접 호출

MAIN_TITLE = os.getenv("KAKAO_MAIN_TITLE", "카카오톡")
INPUT_CLASS = os.getenv("KAKAO_INPUT_CLASS", "RichEdit50W")
LIST_CLASS = os.getenv("KAKAO_LIST_CLASS", "EVA_VH_ListControl_Dblclk")
SEARCH_PATH = [c for c in os.getenv("KAKAO_SEARCH_PATH", "EVA_ChildWindow,EVA_Window,Edit").split(",") if c]
SEND_INTERVAL = float(os.getenv("KAKAO_SEND_INTERVAL", "1.5"))  # 메시지 사이 최소 간격(초)
MAX_LEN = int(os.getenv("KAKAO_MAX_LEN", "0"))  # 0 = 제한 없음
MY_NAME = os.getenv("KAKAO_MY_NAME", "")  # wait_for_reply에서 내 메시지를 거를 때 사용

_lock = threading.RLock()  # 클립보드·키 입력이 섞이지 않도록 한 번에 한 작업만
_last_send = 0.0


class KakaoError(RuntimeError):
    pass


# ---------- 창 찾기 ----------

def main_window() -> int:
    hwnd = win32gui.FindWindow(None, MAIN_TITLE)
    if not hwnd:
        raise KakaoError("카카오톡 메인 창을 찾지 못했습니다. PC 카카오톡을 실행하고 로그인해 두세요.")
    return hwnd


def _pid(hwnd: int) -> int:
    return win32process.GetWindowThreadProcessId(hwnd)[1]


def _descendants(parent: int, cls: str) -> list[int]:
    found: list[int] = []

    def cb(child, _):
        if win32gui.GetClassName(child).lower() == cls.lower():  # 클래스 이름은 대소문자 구분 없음
            found.append(child)
        return True

    try:
        win32gui.EnumChildWindows(parent, cb, None)
    except win32gui.error:
        pass
    return found


def _descendant(parent: int, cls: str) -> int:
    direct = win32gui.FindWindowEx(parent, 0, cls, None)
    if direct:
        return direct
    found = _descendants(parent, cls)
    if not found:
        raise KakaoError(f"창 안에서 '{cls}' 컨트롤을 찾지 못했습니다. kakaotalk-mcp-diag로 클래스 이름을 확인하세요.")
    return found[0]


def _chat_windows() -> dict[str, int]:
    main = main_window()
    pid = _pid(main)
    rooms: dict[str, int] = {}

    def cb(hwnd, _):
        if hwnd != main and _pid(hwnd) == pid:
            title = win32gui.GetWindowText(hwnd)
            if title and (win32gui.FindWindowEx(hwnd, 0, INPUT_CLASS, None) or _descendants(hwnd, INPUT_CLASS)):
                rooms.setdefault(title, hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return rooms


def list_chat_windows() -> list[str]:
    return sorted(_chat_windows())


def chat_window(room: str) -> int:
    hwnd = _chat_windows().get(room)
    if not hwnd:
        raise KakaoError(f"'{room}' 대화방 창이 열려 있지 않습니다. open_chat으로 먼저 여세요.")
    return hwnd


# ---------- 키·클립보드 ----------

def _post_key(hwnd: int, key: int, modifiers: tuple[int, ...] = ()) -> None:
    """포커스를 뺏지 않고 특정 컨트롤에 키 신호를 보낸다."""
    lparam = win32api.MAKELONG(0, win32api.MapVirtualKey(key, 0))
    if not modifiers:
        win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, key, lparam)
        time.sleep(0.02)
        win32api.PostMessage(hwnd, win32con.WM_KEYUP, key, lparam | 0xC0000000)
        return
    # Ctrl 같은 조합키는 대상 스레드의 키보드 상태를 잠깐 바꿔서 전달한다
    target_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
    my_tid = win32api.GetCurrentThreadId()
    win32process.AttachThreadInput(my_tid, target_tid, True)
    try:
        old = (ctypes.c_ubyte * 256)()
        _user32.GetKeyboardState(old)
        new = (ctypes.c_ubyte * 256)(*old)
        for mod in modifiers:
            new[mod] = 0x80
        _user32.SetKeyboardState(new)
        time.sleep(0.02)
        win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, key, lparam)
        time.sleep(0.02)
        win32api.PostMessage(hwnd, win32con.WM_KEYUP, key, lparam | 0xC0000000)
        time.sleep(0.1)
        _user32.SetKeyboardState(old)
    finally:
        win32process.AttachThreadInput(my_tid, target_tid, False)


DEBUG = os.getenv("KAKAO_DEBUG", "0") not in ("0", "false", "off")


def _debug(*args) -> None:
    if DEBUG:
        print("[debug]", *args, file=sys.stderr, flush=True)


def _get_text(hwnd: int) -> str:
    """다른 프로세스의 입력칸 내용을 읽는다 (WM_GETTEXT는 시스템이 프로세스 사이를 대신 옮겨 준다)."""
    n = _user32.SendMessageW(hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 2)
    _user32.SendMessageW(hwnd, win32con.WM_GETTEXT, n + 2, buf)
    return buf.value


def _was_sent(edit: int, text: str) -> bool:
    """넣은 글자가 입력칸에서 사라졌으면 전송된 것으로 본다."""
    current = _get_text(edit)
    _debug(f"입력칸 상태: 길이={len(current)} 내용={current[:40]!r}")
    return text.strip() not in current


ALLOW_FOREGROUND = os.getenv("KAKAO_ALLOW_FOREGROUND", "1") not in ("0", "false", "off")
_preferred_method: tuple[str, str] | None = None  # 한 번 성공한 방식을 다음부터 먼저 쓴다


def _enter_post_plain(edit: int, chat: int) -> None:
    ret = win32con.VK_RETURN
    win32api.PostMessage(edit, win32con.WM_KEYDOWN, ret, 0)
    time.sleep(0.02)
    win32api.PostMessage(edit, win32con.WM_KEYUP, ret, 0)


def _enter_post_scan(edit: int, chat: int) -> None:
    _post_key(edit, win32con.VK_RETURN)


def _enter_foreground(edit: int, chat: int) -> None:
    """대화방 창을 잠깐 앞으로 가져와 실제 Enter 키를 누르고, 원래 창으로 돌려놓는다."""
    previous = win32gui.GetForegroundWindow()
    target_tid = win32process.GetWindowThreadProcessId(chat)[0]
    my_tid = win32api.GetCurrentThreadId()
    win32process.AttachThreadInput(my_tid, target_tid, True)
    try:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)  # Alt를 눌렀다 떼면 포그라운드 전환 제한이 풀린다
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32gui.SetForegroundWindow(chat)
        win32gui.SetFocus(edit)
        time.sleep(0.05)
        win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
        win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)
    finally:
        win32process.AttachThreadInput(my_tid, target_tid, False)
        if previous and previous != chat:
            try:
                win32gui.SetForegroundWindow(previous)
            except win32gui.error:
                pass


_ENTER = {"post": _enter_post_plain, "post-scan": _enter_post_scan, "foreground": _enter_foreground}

EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2


def _input_settext(edit: int, text: str) -> None:
    """입력칸 내용을 통째로 바꾼다 (가장 빠르지만 카톡이 '입력'으로 인식하지 않을 수 있음)."""
    win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, text)


def _input_replacesel(edit: int, text: str) -> None:
    """사용자가 입력한 것처럼 선택 영역을 바꾼다 (실행 취소 가능 = 사용자 입력과 같은 경로)."""
    win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, "")
    win32gui.SendMessage(edit, EM_SETSEL, 0, -1)
    _user32.SendMessageW(edit, EM_REPLACESEL, 1, ctypes.c_wchar_p(text))


def _input_wmchar(edit: int, text: str) -> None:
    """한 글자씩 타이핑 신호를 보낸다 (가장 느리지만 실제 타이핑과 가장 비슷함)."""
    win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, "")
    data = text.replace("\r\n", "\n").encode("utf-16-le")
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i + 2], "little")  # 이모지 같은 문자는 두 단위로 나눠 보낸다
        if unit == 0x0A:
            continue  # 줄바꿈 신호는 전송으로 처리될 수 있어 타이핑 방식에서는 뺀다
        _user32.SendMessageW(edit, win32con.WM_CHAR, unit, 1)


# 카카오톡 PC(2026-11 확인)에서는 replacesel + 백그라운드 Enter(post)로 전송됨. settext는 화면에만 글자가 보이고 전송되지 않음
_INPUT = {"replacesel": _input_replacesel, "wmchar": _input_wmchar, "settext": _input_settext}


def _send_text(edit: int, chat: int, text: str) -> str:
    """글자를 넣고 Enter로 전송한다. 넣은 글자가 입력칸에서 사라지면 전송된 것으로 본다.
    카톡 버전마다 받아들이는 방식이 달라 (글자 넣기 × Enter) 조합을 차례로 시도한다.
    성공한 조합은 기억해 두고 다음부터 먼저 쓴다."""
    global _preferred_method
    enters = ["post", "post-scan"] + (["foreground"] if ALLOW_FOREGROUND else [])
    combos = [(i, e) for e in enters for i in _INPUT]  # 화면을 건드리지 않는 조합부터
    if _preferred_method in combos:
        combos.remove(_preferred_method)
        combos.insert(0, _preferred_method)
    for input_name, enter_name in combos:
        label = f"{input_name}+{enter_name}"
        _INPUT[input_name](edit, text)
        time.sleep(0.15)
        _debug(f"[{label}] 글자 넣은 뒤")
        if _was_sent(edit, text):
            _debug(f"[{label}] 입력칸에서 글자가 읽히지 않아 건너뜀")
            continue
        _ENTER[enter_name](edit, chat)
        for _ in range(4):
            time.sleep(0.25)
            if _was_sent(edit, text):
                _debug(f"[{label}] 성공")
                _preferred_method = (input_name, enter_name)
                return label
        _debug(f"[{label}] 실패")
        win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, "")
    win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, "")  # 못 보낸 글자를 입력칸에 남기지 않는다
    raise KakaoError("전송되지 않았습니다. 시도한 조합: " + ", ".join(f"{i}+{e}" for i, e in combos))


def _open_clipboard() -> None:
    for _ in range(20):
        try:
            win32clipboard.OpenClipboard()
            return
        except win32clipboard.error:
            time.sleep(0.05)
    raise KakaoError("클립보드를 열지 못했습니다. 다른 프로그램이 클립보드를 쓰고 있는지 확인하세요.")


def _get_clipboard() -> str | None:
    _open_clipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    finally:
        win32clipboard.CloseClipboard()


def _set_clipboard(text: str | None) -> None:
    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        if text is not None:
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


# ---------- 동작 ----------

def open_chat(name: str, timeout: float = 6.0) -> str:
    """친구 이름(또는 대화방 이름)으로 검색해 대화방 창을 연다."""
    with _lock:
        if name in _chat_windows():
            return name
        main = main_window()
        hwnd = main
        for cls in SEARCH_PATH:
            nxt = win32gui.FindWindowEx(hwnd, 0, cls, None)
            if not nxt:
                found = _descendants(hwnd, cls)
                nxt = found[0] if found else 0
            if not nxt:
                raise KakaoError(f"메인 창에서 검색칸 경로({'>'.join(SEARCH_PATH)})를 찾지 못했습니다. "
                                 "친구 탭을 연 상태인지 확인하고, diag로 경로를 확인하세요.")
            hwnd = nxt
        win32api.SendMessage(hwnd, win32con.WM_SETTEXT, 0, name)
        try:
            time.sleep(0.8)
            _post_key(hwnd, win32con.VK_RETURN)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(0.3)
                if name in _chat_windows():
                    return name
        finally:
            # 성공하든 실패하든 검색칸을 비워 친구 목록을 원래대로 돌린다
            win32api.SendMessage(hwnd, win32con.WM_SETTEXT, 0, "")
            # Esc는 카톡 메인 창을 숨기므로 보내지 않는다. 숨겨졌다면 포커스를 뺏지 않고 다시 보이게 한다
            if not win32gui.IsWindowVisible(main):
                win32gui.ShowWindow(main, win32con.SW_SHOWNOACTIVATE)
        raise KakaoError(f"'{name}' 대화방이 열리지 않았습니다. 친구 목록에 있는 이름인지 확인하세요. "
                         "나와의 채팅은 검색으로 열리지 않으니 직접 열어 두세요.")


def send_message(room: str, text: str) -> str:
    """메시지를 보내고, 전송에 성공한 Enter 방식 이름을 돌려준다."""
    global _last_send
    if not text.strip():
        raise KakaoError("빈 메시지는 보낼 수 없습니다.")
    if MAX_LEN and len(text) > MAX_LEN:
        raise KakaoError(f"메시지가 {len(text)}자로 제한 {MAX_LEN}자를 넘습니다.")
    with _lock:
        wait = SEND_INTERVAL - (time.monotonic() - _last_send)
        if wait > 0:
            time.sleep(wait)
        try:
            chat = chat_window(room)
        except KakaoError:
            open_chat(room)  # 창이 없으면 친구 이름으로 검색해서 연다
            time.sleep(0.5)  # 새 창의 입력칸이 준비될 때까지 잠깐 기다린다
            chat = chat_window(room)
        edit = _descendant(chat, INPUT_CLASS)
        try:
            return _send_text(edit, chat, text.replace("\r\n", "\n").replace("\n", "\r\n"))
        finally:
            _last_send = time.monotonic()


def read_raw(room: str) -> str:
    """대화방에 불러와진 대화를 텍스트로 복사해 온다. 사용자 클립보드 텍스트는 되돌린다."""
    with _lock:
        chat = _descendant(chat_window(room), LIST_CLASS)
        saved = _get_clipboard()
        marker = f"__kakaotalk_mcp_{time.time_ns()}__"
        _set_clipboard(marker)
        try:
            _post_key(chat, ord("A"), (win32con.VK_CONTROL,))
            time.sleep(0.1)
            _post_key(chat, ord("C"), (win32con.VK_CONTROL,))
            text = None
            for _ in range(30):
                time.sleep(0.1)
                current = _get_clipboard()
                if current and current != marker:
                    text = current
                    break
        finally:
            _set_clipboard(saved)
        if text is None:
            raise KakaoError("대화 내용을 복사하지 못했습니다. 대화방 창이 최소화돼 있지 않은지, "
                             "diag로 대화 목록 클래스 이름을 확인하세요.")
        return text


def read_messages(room: str, last_n: int = 30) -> list[dict]:
    msgs = parse_messages(read_raw(room))
    return msgs[-last_n:] if last_n > 0 else msgs


def wait_for_reply(room: str, timeout: float = 90.0, my_name: str = "", poll: float = 3.0) -> list[dict]:
    """상대가 새 메시지를 보낼 때까지 기다렸다가, 답이 다 들어오면(한 번 더 확인해도 그대로면) 돌려준다."""
    me = my_name or MY_NAME
    before = parse_messages(read_raw(room))
    deadline = time.monotonic() + timeout
    pending: list[dict] = []
    while time.monotonic() < deadline:
        time.sleep(poll)
        new = [m for m in messages_after(before, parse_messages(read_raw(room))) if not me or m["sender"] != me]
        if new and new == pending:
            return new  # 두 번 연속 같으면 답이 끝났다고 본다
        pending = new
    return pending  # 시간 초과: 지금까지 온 것만 (없으면 빈 목록)
