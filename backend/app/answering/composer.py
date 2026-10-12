from __future__ import annotations

import re
from pydantic import BaseModel, Field
from .citation_verifier import CitationVerifier


CATEGORY_LABELS = {
    "food.spiciness": "飲食辣度",
    "availability.next_week": "下週行程",
    "plan.birthday": "生日旅行",
    "event.anniversary": "週年紀念",
}


class AnswerRewrite(BaseModel):
    answer: str = Field(min_length=1, max_length=1200)


class AnswerService:
    def __init__(self, repository, provider=None):
        self.repository = repository
        self.provider = provider
        self.verifier = CitationVerifier()

    def answer(self, conversation_id: str, question: str) -> dict:
        category = self.classify(question)
        if category:
            facts = self.repository.facts(conversation_id, category)
            current = next((f for f in reversed(facts) if f["status"] == "current"), None)
            uncertain = [f for f in facts if f["status"] == "uncertain"]
            if current:
                citations = self._citations(current["source_message_ids"])
                if citations:
                    return self._with_local_model({
                        "status": "supported", "answer": current["display_value"] + "。", "citations": citations,
                        "current_fact": current, "history": facts,
                        "explanation": "已比對同主體、同類別的時序記憶，並只使用可驗證的原始訊息。",
                    }, question)
            if uncertain:
                citations = self._citations([mid for f in uncertain for mid in f["source_message_ids"]])
                return {"status": "ambiguous", "answer": "對話中有相關線索，但不足以判定目前狀態。", "citations": citations,
                        "current_fact": None, "history": facts, "explanation": "相關敘述帶有不確定語氣，沒有更明確的新狀態。"}

        if re.search(r"答應|承諾|我說要|餐廳.*訂", question):
            items = self.repository.commitments(conversation_id)
            if items:
                item = items[-1]
                citations = self._citations([item["source_message_id"]] + ([item["completed_message_id"]] if item.get("completed_message_id") else []))
                if citations:
                    status = {"open": "待完成", "done": "已完成", "cancelled": "已取消"}.get(item["status"], "不確定")
                    return self._with_local_model({"status": "supported", "answer": f'{item["who"]}承諾{item["action"]}，目前為{status}。', "citations": citations,
                            "current_fact": None, "history": [], "explanation": "承諾與後續完成訊息分別保存。"}
                            , question)

        terms = self.keywords(question)
        is_discovery = bool(re.search(r"找|搜尋|哪一則|哪句|提到|原文|訊息", question))
        matches = []
        if terms:
            query = " ".join(terms)
            matches = self.repository.semantic_search(conversation_id, query, 5)
            if is_discovery:
                lexical = self.repository.fts_search(conversation_id, query, 5)
                seen = {m["id"] for m in matches}
                matches = lexical + [m for m in matches if m["id"] not in seen]
        if matches:
            citations = self._citations([m["id"] for m in matches])
            if citations:
                return {"status": "supported", "answer": f"找到 {len(citations)} 則可能相關的原始訊息。", "citations": citations,
                        "current_fact": None, "history": [], "explanation": "這是原始訊息的文字檢索結果，未加入額外推論。"}
        return {"status": "not_found", "answer": "這段對話裡沒有足夠證據可以回答。", "citations": [], "current_fact": None,
                "history": [], "explanation": "RecallSidecar 不會用模型常識或猜測補上缺少的內容。"}

    def _with_local_model(self, result: dict, question: str) -> dict:
        """Use Qwen only as a bounded wording layer; facts and citations stay authoritative."""
        result["llm_used"] = False
        if not self.provider or not getattr(self.provider, "supports_generation", False) or not result.get("citations"):
            return result
        evidence = "\n".join(
            f'- {c["message_id"]} ({c["speaker"]}, {c["timestamp"]}): {c["quote"]}'
            for c in result["citations"][:5]
        )
        prompt = (
            "你是 RecallSidecar 的本地回答格式化器。只能根據已驗證答案與證據改寫，"
            "不得新增日期、地點、人名、數字或推論；不要提及你是模型。請使用繁體中文，保留原意，"
            "只輸出 JSON：{\\\"answer\\\":\\\"...\\\"}。\\n"
            f"問題：{question}\\n已驗證答案：{result['answer']}\\n證據：\\n{evidence}"
        )
        try:
            rewritten = self.provider.generate_structured(prompt, AnswerRewrite)
            answer = rewritten.answer.strip()
            if answer and len(answer) <= 1200:
                result["answer"] = answer
                result["llm_used"] = True
                result["llm_provider"] = getattr(self.provider, "name", "local")
        except Exception:
            # Local model startup/network/format errors must not break core query.
            result["llm_fallback"] = True
        return result

    def _citations(self, ids: list[str]) -> list[dict]:
        raw=[]
        for mid in ids:
            if message := self.repository.message(mid):
                raw.append({"message_id": mid, "speaker": message["sender"], "timestamp": message["timestamp"], "quote": message["content"]})
        return self.verifier.verify(raw, self.repository.message)

    @staticmethod
    def classify(question: str) -> str | None:
        if re.search(r"辣|spicy", question, re.I): return "food.spiciness"
        if re.search(r"生日|旅行|去哪|花蓮|台南|宜蘭", question): return "plan.birthday"
        if re.search(r"沒空|哪天|星期|禮拜|有空", question): return "availability.next_week"
        if re.search(r"週年|紀念", question): return "event.anniversary"
        return None

    @staticmethod
    def keywords(question: str) -> list[str]:
        stop = {"請", "幫我", "找", "訊息", "哪裡", "什麼", "她", "他", "我們", "是否", "有沒有"}
        cleaned = re.sub(r"[？?，。！!、]", " ", question)
        return [x for x in cleaned.split() if len(x) > 1 and x not in stop]
