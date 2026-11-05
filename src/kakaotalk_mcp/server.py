"""카카오톡 MCP 서버 (stdio)."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import kakao

mcp = FastMCP("kakaotalk")


@mcp.tool()
def list_chats() -> list[str]:
    """지금 열려 있는 카카오톡 대화방 창 이름 목록."""
    return kakao.list_chat_windows()


@mcp.tool()
def open_chat(name: str) -> str:
    """친구 이름이나 대화방 이름으로 검색해 대화방 창을 연다. 이미 열려 있으면 그대로 둔다."""
    return f"'{kakao.open_chat(name)}' 대화방이 열려 있습니다."


@mcp.tool()
def send_message(room: str, text: str) -> str:
    """대화방(room = 친구 이름 또는 창 제목)에 메시지를 보낸다. 창이 닫혀 있으면 검색해서 자동으로 연다. 
    나와의 채팅은 자동으로 열리지 않으니 미리 열어 둘 것. 줄바꿈은 그대로 보낸다."""
    method = kakao.send_message(room, text)
    return f"'{room}'에 {len(text)}자를 보냈습니다. (Enter 방식: {method})"


@mcp.tool()
def read_messages(room: str, last_n: int = 30) -> list[dict]:
    """대화방의 최근 메시지를 읽는다. 각 항목은 date, sender, time, text. last_n=0이면 불러온 전체."""
    return kakao.read_messages(room, last_n)


@mcp.tool()
def wait_for_reply(room: str, timeout_sec: int = 90, my_name: str = "") -> list[dict]:
    """상대의 새 답장이 올 때까지 기다렸다가 새 메시지만 돌려준다. my_name을 주면 내 메시지는 뺀다.
    시간 안에 답이 없으면 빈 목록."""
    return kakao.wait_for_reply(room, float(timeout_sec), my_name)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
