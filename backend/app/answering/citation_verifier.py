class CitationVerifier:
    @staticmethod
    def verify(citations: list[dict], message_lookup) -> list[dict]:
        verified = []
        for citation in citations:
            source = message_lookup(citation.get("message_id", ""))
            quote = citation.get("quote", "")
            if source and quote and quote in source["content"]:
                verified.append({
                    "message_id": source["id"], "speaker": source["sender"],
                    "timestamp": source["timestamp"], "quote": quote,
                })
        return verified

