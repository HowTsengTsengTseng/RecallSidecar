import unittest
from app.memory.extractor import MemoryExtractor


def msg(i, sender, timestamp, content):
    return {"id": f"m{i}", "sender": sender, "timestamp": timestamp, "content": content}


class MemoryTest(unittest.TestCase):
    def test_temporal_preference_change(self):
        facts, _ = MemoryExtractor().analyze([
            msg(1, "Alice", "2026-03-03T10:00:00+08:00", "我完全不吃辣，小辣都不行"),
            msg(2, "Alice", "2026-08-14T10:00:00+08:00", "我現在可以吃一點小辣"),
        ])
        self.assertEqual([x["status"] for x in facts], ["superseded", "current"])
        self.assertEqual(facts[0]["valid_to"], facts[1]["valid_from"])
        self.assertEqual(facts[1]["supersedes_id"], facts[0]["id"])

    def test_people_do_not_supersede_each_other(self):
        facts, _ = MemoryExtractor().analyze([
            msg(1, "Alice", "2026-01-01T10:00:00+08:00", "我完全不吃辣"),
            msg(2, "小宇", "2026-01-02T10:00:00+08:00", "我可以吃一點小辣"),
        ])
        self.assertEqual([x["status"] for x in facts], ["current", "current"])

    def test_tentative_plan_then_booking(self):
        facts, _ = MemoryExtractor().analyze([
            msg(1, "Alice", "2026-01-01T10:00:00+08:00", "生日旅行也許去台南"),
            msg(2, "Alice", "2026-01-02T10:00:00+08:00", "生日旅行確定改去花蓮，我已經訂好車票了"),
        ])
        self.assertEqual(len(facts), 2)
        self.assertEqual(facts[-1]["status"], "current")
        self.assertEqual(facts[-1]["normalized_value"], "destination:花蓮")

    def test_quoted_old_statement_is_ignored(self):
        facts, _ = MemoryExtractor().analyze([
            msg(1, "Alice", "2026-01-01T10:00:00+08:00", "我可以吃一點小辣"),
            msg(2, "小宇", "2026-01-02T10:00:00+08:00", "引用：我完全不吃辣"),
        ])
        self.assertEqual(len(facts), 1)


if __name__ == "__main__": unittest.main()
