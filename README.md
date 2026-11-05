# kakaotalk-mcp

PC 카카오톡을 **윈도우 메시지**로 조작하는 MCP 서버입니다. 화면을 캡처하지 않고 마우스도 움직이지 않아서, 에이전트가 카톡을 쓰는 동안에도 다른 작업을 할 수 있습니다.

> 카카오와 관계없는 비공식 도구입니다. 카카오톡 이용약관은 자동화된 사용을 제한할 수 있으니 본인 계정에서 본인 책임으로 사용하세요. 스팸이나 대량 발송 용도로는 쓰지 마세요.

## 동작 방식

```
LLM (Claude Code 등) ──MCP──▶ kakaotalk-mcp ──윈도우 메시지──▶ PC 카카오톡 창
   다음 말을 정함               send / read                       입력칸 · 대화 목록
```

- **보내기**: 대화방 창의 입력칸(`RichEdit50W`)에 사용자 입력과 같은 경로(`EM_REPLACESEL`)로 글자를 넣고 Enter 신호를 보냅니다. 입력칸이 비는 것을 확인해 실제 전송 여부를 판단하고, 안 되면 다른 방식으로 자동 재시도합니다.
- **읽기**: 대화 목록(`EVA_VH_ListControl_Dblclk`)에 Ctrl+A, Ctrl+C 신호를 보내 클립보드로 텍스트를 받습니다. 받은 뒤에는 원래 클립보드의 텍스트를 되돌려 놓습니다.
- **판단은 LLM 몫**: 이 서버는 보내고 읽기만 합니다. 무엇을 물을지는 연결한 LLM이 정합니다.

## 준비물

- Windows 10/11
- PC 카카오톡 (실행하고 로그인한 상태)
- [uv](https://docs.astral.sh/uv/) (Python 3.10 이상을 알아서 받아 줍니다)

## 설치

```powershell
git clone https://github.com/jjround/kakaotalk-mcp.git
cd kakaotalk-mcp
uv sync
```

## 먼저 진단해 보기

카카오톡 버전에 따라 창 구조가 다를 수 있습니다. MCP에 연결하기 전에 진단 도구로 확인하세요. 테스트는 **나와의 채팅**에서 하는 것이 안전합니다. 나와의 채팅방의 창 제목은 보통 내 카톡 이름입니다.

```powershell
uv run kakaotalk-mcp-diag                       # 메인 창 구조, 열린 대화방
uv run kakaotalk-mcp-diag "내 이름" --open       # 검색해서 대화방 열기
uv run kakaotalk-mcp-diag "내 이름" --send "테스트"
uv run kakaotalk-mcp-diag "내 이름" --read
```

`--read`에서 메시지가 보이면 준비가 끝난 것입니다.

## Claude Code에 연결

```powershell
claude mcp add kakaotalk -- uv --directory C:\경로\kakaotalk-mcp run kakaotalk-mcp
```

Claude 데스크톱 앱에서는 설정의 개발자 메뉴에서 설정 파일(`claude_desktop_config.json`)을 열고 아래처럼 추가합니다.

```json
{
  "mcpServers": {
    "kakaotalk": {
      "command": "uv",
      "args": ["--directory", "C:\\경로\\kakaotalk-mcp", "run", "kakaotalk-mcp"],
      "env": { "KAKAO_MY_NAME": "내 카톡 이름" }
    }
  }
}
```

## 도구

| 도구 | 하는 일 |
| --- | --- |
| `list_chats()` | 열려 있는 대화방 창 이름 목록 |
| `open_chat(name)` | 친구·대화방 이름으로 검색해서 창 열기 |
| `send_message(room, text)` | 메시지 보내기 | 창이 닫혀 있으면 자동으로 엶 |
| `read_messages(room, last_n=30)` | 최근 메시지 읽기 (`date`, `sender`, `time`, `text`) |
| `wait_for_reply(room, timeout_sec=90, my_name="")` | 상대 답장이 올 때까지 기다렸다가 새 메시지만 반환 |

## 설정 (환경 변수)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `KAKAO_MY_NAME` | (없음) | 내 카톡 이름. `wait_for_reply`에서 내 메시지를 거를 때 사용 |
| `KAKAO_SEND_INTERVAL` | `1.5` | 메시지 사이 최소 간격(초) |
| `KAKAO_MAX_LEN` | `0` | 메시지 최대 글자 수 (0 = 제한 없음) |
| `KAKAO_MAIN_TITLE` | `카카오톡` | 메인 창 제목 |
| `KAKAO_INPUT_CLASS` | `RichEdit50W` | 입력칸 클래스 |
| `KAKAO_LIST_CLASS` | `EVA_VH_ListControl_Dblclk` | 대화 목록 클래스 |
| `KAKAO_SEARCH_PATH` | `EVA_ChildWindow,EVA_Window,Edit` | 메인 창에서 검색칸까지의 클래스 경로 |

진단 결과가 기본값과 다르면 위 변수로 바꿔 주세요.

## 사용 예 (Claude Code에게)

> `open_chat`으로 "홍길동" 방을 열고, 다음 주 일정을 물어봐. `wait_for_reply`로 답을 받고, 빠진 날짜가 있으면 다시 물어봐. 받은 내용은 `notes/홍길동.md`에 정리해.

## 한계

- **클립보드**: 읽을 때마다 잠깐 클립보드를 씁니다. 그 순간 복사·붙여넣기를 하면 섞일 수 있습니다. 텍스트가 아닌 클립보드 내용(이미지 등)은 되돌리지 못합니다.
- **창 상태**: 대화방 창이 열려 있어야 합니다. 최소화하면 읽기가 실패할 수 있으니 다른 창 뒤에 두세요.
- **불러온 범위**: 대화방 창에 불러와진 메시지만 읽습니다. 아주 오래된 메시지는 창을 위로 스크롤해야 나옵니다.
- **이름 중복**: 같은 이름의 대화방이 여러 개면 처음 찾은 창을 씁니다.
- **업데이트**: 카카오톡 업데이트로 창 구조가 바뀌면 동작이 멈출 수 있습니다. 진단 도구로 클래스 이름을 다시 확인하세요.
- **사진·파일**: 텍스트 메시지만 다룹니다.

## 테스트

```powershell
uv run python -m unittest discover -s tests
```

파싱 테스트는 Windows가 아니어도 돌아갑니다.

## 라이선스

MIT
