from pathlib import Path
import json
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.answering import AnswerService
from app.db import Repository
from app.demo import generate_messages
from app.memory import MemoryExtractor


def main():
    questions_path = Path(__file__).with_name("questions.json")
    if not questions_path.exists():
        print("Run evaluation/generate.py first"); raise SystemExit(2)
    with tempfile.TemporaryDirectory() as tmp:
        repo=Repository(Path(tmp)/"eval.db")
        cid=repo.create_conversation("evaluation","synthetic_demo",None,"Asia/Taipei")
        repo.insert_messages(cid,generate_messages())
        facts,commitments=MemoryExtractor().analyze(repo.messages(cid,100000))
        repo.replace_analysis(cid,facts,commitments)
        service=AnswerService(repo);questions=json.loads(questions_path.read_text())
        status_ok=citation_ok=current_ok=0
        for question in questions:
            result=service.answer(cid,question["question"])
            status_ok += result["status"]==question["expected_status"]
            citation_ok += result["status"]!="supported" or bool(result["citations"])
            current_ok += question["expected_concept"] is None or question["expected_concept"] in result["answer"]
        total=len(questions)
        print(json.dumps({"questions":total,"status_accuracy":status_ok/total,"citation_existence_rate":citation_ok/total,"current_concept_accuracy":current_ok/total},indent=2))


if __name__ == "__main__": main()
