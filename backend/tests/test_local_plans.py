import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.answering import AnswerService
from app.db import Repository
from app.demo import generate_messages
from app.memory.local_plan import LocalPlanExtractor, PlanExtraction, time_window


class FakePlanProvider:
    def generate_structured(self, prompt, schema):
        self_prompt = prompt.split("原文：", 1)[-1]
        match = re.search(r"下週要去燙頭髮", self_prompt)
        return PlanExtraction(has_plan=bool(match), activity="要去燙頭髮" if match else "",
                              time_expression="下週" if match else "")


class LocalPlanTest(unittest.TestCase):
    def test_new_plan_survives_large_import_and_has_source(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Repository(Path(folder) / "plans.db")
            cid = repo.create_conversation("Alice 與小宇", "synthetic_demo", "test.txt", "Asia/Taipei")
            inserted, _ = repo.insert_messages(cid, generate_messages())
            self.assertEqual(inserted, 5000)
            timestamp = datetime.now().astimezone().isoformat()
            inserted, ids = repo.insert_messages(cid, [{"sender": "Alice", "timestamp": timestamp,
                "type": "text", "content": "我下週要去燙頭髮", "source_locator": {"type": "test"}}])
            self.assertEqual(inserted, 1)
            message = repo.message(ids[0])
            plan = LocalPlanExtractor(FakePlanProvider()).extract(message)
            self.assertEqual(plan["start_date"], time_window("下週", datetime.fromisoformat(timestamp))[0])
            repo.save_plan_extraction(message, "qwen2.5:1.5b", plan)
            _, old_ids = repo.insert_messages(cid, [{"sender": "Alice", "timestamp": "2026-01-01T09:00:00+08:00",
                "type": "text", "content": "我下週要去燙頭髮", "source_locator": {"type": "old_test"}}])
            old_message = repo.message(old_ids[0])
            repo.save_plan_extraction(old_message, "qwen2.5:1.5b", LocalPlanExtractor(FakePlanProvider()).extract(old_message))
            result = AnswerService(repo).answer(cid, "Alice 下週有什麼計劃？")
            self.assertEqual(result["status"], "supported")
            self.assertIn("燙頭髮", result["answer"])
            self.assertEqual(result["citations"][0]["message_id"], ids[0])


if __name__ == "__main__":
    unittest.main()
