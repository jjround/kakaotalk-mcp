import unittest

from kakaotalk_mcp.parse import messages_after, parse_messages

SAMPLE = """홍길동 님과 카카오톡 대화
2026년 10월 31일 토요일
[김철수] [오후 2:28] 내일 회의 몇 시죠?
[홍길동] [오후 2:29] 오후 3시입니다
장소는 3층 회의실이에요
[홍길동] [오후 2:29] 자료 보내드릴게요
"""


class ParseTest(unittest.TestCase):
    def test_parse(self):
        msgs = parse_messages(SAMPLE.replace("\n", "\r\n"))
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["sender"], "김철수")
        self.assertEqual(msgs[1]["text"], "오후 3시입니다\n장소는 3층 회의실이에요")
        self.assertEqual(msgs[2]["date"], "2026년 10월 31일 토요일")
        self.assertEqual(msgs[2]["time"], "오후 2:29")

    def test_after(self):
        before = parse_messages(SAMPLE)
        after = parse_messages(SAMPLE + "[홍길동] [오후 2:31] 보냈습니다\n")
        new = messages_after(before, after)
        self.assertEqual([m["text"] for m in new], ["보냈습니다"])
        self.assertEqual(messages_after(before, before), [])
        self.assertEqual(len(messages_after([], before)), 3)

    def test_after_when_old_messages_unloaded(self):
        before = parse_messages(SAMPLE)
        after = before[1:] + parse_messages("[홍길동] [오후 2:35] 추가\n")
        self.assertEqual([m["text"] for m in messages_after(before, after)], ["추가"])


if __name__ == "__main__":
    unittest.main()
