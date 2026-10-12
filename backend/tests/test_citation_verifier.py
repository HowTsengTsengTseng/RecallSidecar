import unittest
from app.answering.citation_verifier import CitationVerifier


class CitationVerifierTest(unittest.TestCase):
    def test_removes_quote_not_present_in_source(self):
        source = {"id": "m1", "sender": "Alice", "timestamp": "2026-01-01T00:00:00+08:00", "content": "原始文字"}
        lookup = lambda mid: source if mid == "m1" else None
        citations = [
            {"message_id": "m1", "quote": "原始文字"},
            {"message_id": "m1", "quote": "模型捏造文字"},
        ]
        result = CitationVerifier.verify(citations, lookup)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["quote"], "原始文字")


if __name__ == "__main__": unittest.main()

