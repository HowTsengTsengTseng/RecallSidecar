import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp.name) / "test.db", static_dir=Path(self.temp.name) / "missing"))

    def tearDown(self): self.temp.cleanup()

    def test_demo_query_update_and_refusal(self):
        seed = self.client.post("/api/demo/seed").json()
        cid = seed["conversation_id"]
        self.assertEqual(seed["message_count"], 5000)
        answer = self.client.post(f"/api/conversations/{cid}/query", json={"question": "Alice 現在可以吃辣嗎？"}).json()
        self.assertEqual(answer["status"], "supported")
        self.assertTrue(answer["citations"])
        self.assertIn(answer["citations"][0]["quote"], self.client.get(f"/api/conversations/{cid}/messages", params={"around": answer["citations"][0]["message_id"]}).text)
        missing = self.client.post(f"/api/conversations/{cid}/query", json={"question": "Alice 的貓叫什麼名字？"}).json()
        self.assertEqual(missing["status"], "not_found")
        self.client.post(f"/api/conversations/{cid}/messages", json={"sender": "Alice", "content": "生日旅行確定改去宜蘭，我已經訂好民宿了"})
        updated = self.client.post(f"/api/conversations/{cid}/query", json={"question": "生日旅行去哪裡？"}).json()
        self.assertIn("宜蘭", updated["answer"])
        changes = self.client.get(f"/api/conversations/{cid}/changes").json()
        travel = next(x for x in changes if x["category"] == "plan.birthday")
        self.assertGreaterEqual(len(travel["history"]), 3)

    def test_import_preview_commit_and_deduplicate(self):
        text = "2026/08/14(五)\n21:32 Alice 測試訊息\n"
        preview = self.client.post("/api/imports/line/preview", json={"filename": "x.txt", "content": text}).json()
        self.assertEqual(preview["message_count"], 1)
        committed = self.client.post("/api/imports/line/commit", json={"preview_id": preview["preview_id"]}).json()
        cid = committed["conversation_id"]
        second_preview = self.client.post("/api/imports/line/preview", json={"filename": "x.txt", "content": text}).json()
        second = self.client.post("/api/imports/line/commit", json={"preview_id": second_preview["preview_id"]}).json()
        self.assertEqual(second["conversation_id"], cid)
        self.assertEqual(second["inserted"], 0)
        self.assertTrue(second["deduplicated"])
        duplicate = self.client.post(f"/api/conversations/{cid}/messages", json={"sender": "Alice", "content": "測試訊息", "timestamp": "2026-08-14T21:32:00+08:00"})
        self.assertEqual(duplicate.status_code, 409)


if __name__ == "__main__": unittest.main()
