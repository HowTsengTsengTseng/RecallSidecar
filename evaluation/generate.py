from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.demo import generate_messages

ROOT = Path(__file__).resolve().parent


def main():
    messages = generate_messages(5000)
    lines = ["[LINE] Alice 與小宇的聊天記錄", "儲存日期：2026/10/11", ""]
    current_date = None
    for message in messages:
        date = message["timestamp"][:10].replace("-", "/")
        if date != current_date:
            lines.extend([date, ""]); current_date = date
        lines.append(f'{message["timestamp"][11:16]}\t{message["sender"]}\t{message["content"]}')
    (ROOT / "synthetic_chat.txt").write_text("\n".join(lines), encoding="utf-8")
    base = [
        {"question": "Alice 現在可以吃辣嗎？", "expected_status": "supported", "expected_concept": "小辣", "expected_source_message_ids": ["msg-4217"]},
        {"question": "下週哪天沒空？", "expected_status": "supported", "expected_concept": "三", "expected_source_message_ids": ["msg-2140"]},
        {"question": "生日旅行去哪？", "expected_status": "supported", "expected_concept": "花蓮", "expected_source_message_ids": ["msg-4550"]},
        {"question": "Alice 的貓叫什麼？", "expected_status": "not_found", "expected_concept": None, "expected_source_message_ids": []},
    ]
    questions=[]
    for _ in range(25):
        for question in base: questions.append({"id": f"q{len(questions)+1:03d}", **question})
    (ROOT / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated {len(messages)} messages and {len(questions)} labeled questions")


if __name__ == "__main__": main()

