import unittest
from app.importers.line_txt import LineTxtImporter


FIXTURE = """[LINE] Alice 與小宇的聊天記錄
儲存日期：2026/10/11

2026/08/14(五)
21:32 Alice 第一行😀 https://example.com
第二行保留
21:34 小宇 [貼圖]
21:35 Alice 已收回訊息
系統無法辨識事件
"""


class LineImporterTest(unittest.TestCase):
    def test_multiline_metadata_and_special_types(self):
        result = LineTxtImporter().parse(FIXTURE, "alice.txt")
        self.assertEqual(result["title"], "Alice 與小宇")
        self.assertEqual(len(result["messages"]), 3)
        self.assertEqual(result["messages"][0]["content"], "第一行😀 https://example.com\n第二行保留")
        self.assertEqual(result["messages"][1]["type"], "attachment")
        self.assertEqual(result["messages"][2]["type"], "deleted")
        self.assertEqual(result["participants"], ["Alice", "小宇"])
        self.assertEqual(result["messages"][0]["source_locator"]["line_end"], 6)


if __name__ == "__main__": unittest.main()

