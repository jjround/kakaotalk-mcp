"""진단·수동 테스트 도구.

    kakaotalk-mcp-diag                      메인 창과 열린 대화방, 컨트롤 구조 출력
    kakaotalk-mcp-diag 방이름               그 대화방 창의 컨트롤 구조 출력
    kakaotalk-mcp-diag 방이름 --read        최근 메시지 10개 읽기
    kakaotalk-mcp-diag 방이름 --send 글     메시지 보내기
    kakaotalk-mcp-diag 이름 --open          검색해서 대화방 열기
"""
from __future__ import annotations

import argparse
import sys

import win32gui

from . import kakao


def tree(hwnd: int, depth: int = 0, max_depth: int = 4) -> None:
    child = win32gui.FindWindowEx(hwnd, 0, None, None)
    while child:
        title = win32gui.GetWindowText(child)[:30]
        print("  " * depth + f"- {win32gui.GetClassName(child)}  '{title}'  hwnd={child}")
        if depth < max_depth:
            tree(child, depth + 1, max_depth)
        child = win32gui.FindWindowEx(hwnd, child, None, None)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="kakaotalk-mcp 진단")
    p.add_argument("room", nargs="?")
    p.add_argument("--read", action="store_true")
    p.add_argument("--send")
    p.add_argument("--open", action="store_true")
    a = p.parse_args()
    kakao.DEBUG = True  # 진단 때는 입력칸 상태를 함께 보여 준다
    sys.stderr.reconfigure(encoding="utf-8")

    try:
        from . import __version__
        print(f"kakaotalk-mcp {__version__}")
        main_hwnd = kakao.main_window()
        print(f"메인 창: hwnd={main_hwnd} class={win32gui.GetClassName(main_hwnd)}")
        if a.open and a.room:
            print(kakao.open_chat(a.room), "열림")
        print("열린 대화방:", kakao.list_chat_windows() or "(없음)")
        if not a.room:
            print("\n[메인 창 구조]  검색칸 경로 기본값:", ">".join(kakao.SEARCH_PATH))
            tree(main_hwnd)
            return
        hwnd = kakao.chat_window(a.room)
        print(f"\n['{a.room}' 창 구조]  입력칸={kakao.INPUT_CLASS}  대화목록={kakao.LIST_CLASS}")
        tree(hwnd)
        if a.send:
            method = kakao.send_message(a.room, a.send)
            print(f"\n보냄: {a.send}  (Enter 방식: {method})")
        if a.read:
            print("\n[최근 메시지]")
            for m in kakao.read_messages(a.room, 10):
                print(f"{m['time']} {m['sender']}: {m['text']}")
    except kakao.KakaoError as e:
        print("오류:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
