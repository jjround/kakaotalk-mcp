"""카카오톡에서 복사한 대화 텍스트를 메시지 목록으로 바꾼다 (Windows 의존성 없음).

PC 카카오톡에서 대화를 전체 선택·복사하면 대략 이런 형식이 나온다.

    2026년 10월 31일 토요일
    [홍길동] [오후 2:29] 내일 회의는 오후 3시입니다
    두 번째 줄은 접두어 없이 이어집니다
    [김철수] [오후 2:30] 감사합니다
"""
from __future__ import annotations

import re

MESSAGE_LINE = re.compile(r"^\[(?P<sender>[^\]]+)\] \[(?P<time>(?:오전|오후) \d{1,2}:\d{2})\] ?(?P<text>.*)$")
DATE_LINE = re.compile(r"^\d{4}년 \d{1,2}월 \d{1,2}일(?: [월화수목금토일]요일)?$")


def parse_messages(raw: str) -> list[dict]:
    """복사한 텍스트 → [{"date", "sender", "time", "text"}, ...] (오래된 것부터)."""
    messages: list[dict] = []
    date = ""
    for line in raw.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if DATE_LINE.match(stripped):
            date = stripped
            continue
        m = MESSAGE_LINE.match(line)
        if m:
            messages.append({"date": date, "sender": m["sender"], "time": m["time"], "text": m["text"]})
        elif messages:
            messages[-1]["text"] += "\n" + line
        # 첫 메시지 앞의 안내 문구 등은 버린다
    for msg in messages:
        msg["text"] = msg["text"].rstrip("\n")
    return messages


def _key(msg: dict) -> tuple:
    return (msg["date"], msg["sender"], msg["time"], msg["text"])


def messages_after(before: list[dict], after: list[dict]) -> list[dict]:
    """before 이후에 새로 생긴 메시지만 돌려준다.

    창에 불러온 범위가 달라져 앞부분이 잘려도 동작하도록, before의 마지막 메시지를
    after에서 뒤에서부터 찾아 그 다음부터를 새 메시지로 본다.
    """
    if not before:
        return list(after)
    last = _key(before[-1])
    for i in range(len(after) - 1, -1, -1):
        if _key(after[i]) == last:
            return list(after[i + 1:])
    # 마지막 메시지를 못 찾으면 (창이 크게 바뀜) 개수 차이만큼 뒤에서 자른다
    extra = len(after) - len(before)
    return list(after[-extra:]) if extra > 0 else []
