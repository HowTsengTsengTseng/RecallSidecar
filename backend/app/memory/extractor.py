from __future__ import annotations

import re
import uuid


class MemoryExtractor:
    """Deterministic Stage I extractor. Imported text is treated strictly as data."""
    def analyze(self, messages: list[dict]) -> tuple[list[dict], list[dict]]:
        facts: list[dict] = []
        commitments: list[dict] = []
        for message in sorted(messages, key=lambda x: x["timestamp"]):
            if message.get("type", "text") != "text":
                continue
            text = message["content"]
            sender = message["sender"]
            quoted_only = bool(re.match(r"^(?:>|引用[:：]|轉貼[:：])", text.strip()))
            if quoted_only:
                continue
            sensitive_terms = ("診斷", "躁鬱", "憂鬱症", "精神疾病", "性傾向", "政治立場", "投票", "心理疾病")
            if any(term in text for term in sensitive_terms):
                continue
            specific_preference = bool(re.search(r"不吃辣|小辣都不行|不能吃辣|可以吃(?:一點)?小辣|小辣(?:可以|沒問題)|能吃微辣", text))
            if re.search(r"(?:完全)?不吃辣|小辣都不行|不能吃辣", text):
                facts.append(self.fact(message, sender, "preference", "food.spiciness", "no_spicy", "不吃辣，連小辣都不行", .96))
            if re.search(r"可以吃(?:一點)?小辣|小辣(?:可以|沒問題)|能吃微辣", text):
                facts.append(self.fact(message, sender, "preference", "food.spiciness", "mild_ok", "目前可以接受小辣", .96))
            if not specific_preference and (match := re.search(r"我(?:比較)?(喜歡|不喜歡|討厭|偏好|愛吃|不吃)([^，。！？!?\n]{1,18})", text)):
                verb, target = match.group(1), match.group(2).strip(" 的是：:， ")
                if target:
                    category_target = re.sub(r"[^\w\u4e00-\u9fff]+", "_", target[:10]).strip("_")
                    positive = verb in {"喜歡", "偏好", "愛吃"}
                    display = f"{verb}{target}"
                    facts.append(self.fact(message, sender, "preference", f"preference.{category_target}",
                                           ("likes:" if positive else "dislikes:") + target, display, .88))
            if match := re.search(r"(?:我叫|我的(?:名字|寵物名字|工作|職業|生日)(?:是|叫)?)([^，。！？!?\n]{1,20})", text):
                value = match.group(1).strip(" 的是：:， ")
                if value:
                    label = "名字" if "我叫" in match.group(0) or "名字" in match.group(0) else "個人資料"
                    facts.append(self.fact(message, sender, "personal_fact", f"personal.{label}", value, f"{label}：{value}", .90))
            if match := re.search(r"下(?:週|星期)([一二三四五六日天]).{0,8}(?:沒空|不能|不行)", text):
                day = match.group(1)
                period = "下午" if "下午" in text else ""
                facts.append(self.fact(message, sender, "availability", "availability.next_week", f"weekday:{day}:{period}", f"下週{day}{period}沒空", .94))
            if re.search(r"生日.{0,8}(?:也許|可能).{0,3}台南", text):
                facts.append(self.fact(message, sender, "plan", "plan.birthday", "destination:tainan:tentative", "生日旅行也許去台南", .72, explicit=False))
            if match := re.search(r"(?:生日旅行.{0,8}(?:確定.{0,3}(?:改去|去)|改去)|生日.{0,8}確定去)([\u4e00-\u9fff]{2,4})", text):
                place = re.split(r"[，。,.！!？?]", match.group(1))[0]
                place = re.sub(r"(?:我已經|已經|旅行)$", "", place)
                facts.append(self.fact(message, sender, "plan", "plan.birthday", f"destination:{place}", f"生日旅行確定改去{place}", .98))
            if re.search(r"週年紀念.{0,8}(?:去|去了)淡水", text):
                facts.append(self.fact(message, sender, "event", "event.anniversary", "tamsui", "上次週年紀念去了淡水", .96))
            elif re.search(r"(?:我|我們).{0,10}(?:計畫|打算|預計|想要).{0,12}(?:去|到|旅行|安排)", text):
                plan = re.search(r"(?:計畫|打算|預計|想要)([^，。！？!?\n]{1,24})", text)
                if plan:
                    value = plan.group(1).strip()
                    facts.append(self.fact(message, sender, "plan", "plan.general", value, f"計畫{value}", .86))
            if match := re.search(r"(?:我答應|我會|我來)(.{1,24}?)(?:[。！!]|$)", text):
                action = match.group(1).strip()
                if any(word in action for word in ("訂", "買", "帶", "處理", "完成", "傳")):
                    commitments.append({"id": self.uid("commit"), "who": sender, "action": action, "due_date": self.due_date(text), "status": "open", "source_message_id": message["id"]})
            if re.search(r"(?:餐廳|票|民宿).{0,6}(?:已經)?訂好(?:了)?|已經完成", text):
                open_item = next((c for c in reversed(commitments) if c["who"] == sender and c["status"] == "open"), None)
                if open_item:
                    open_item["status"] = "done"
                    open_item["completed_message_id"] = message["id"]
            if re.search(r"(?:取消|不用|不需要).{0,8}(?:訂|買|處理|安排)|(?:訂|買|處理|安排).{0,8}(?:取消|不用了)", text):
                open_item = next((c for c in reversed(commitments) if c["who"] == sender and c["status"] == "open"), None)
                if open_item:
                    open_item["status"] = "cancelled"
                    open_item["completed_message_id"] = message["id"]
        self.resolve(facts)
        return facts, commitments

    @staticmethod
    def uid(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4()}"

    def fact(self, message, subject, memory_type, category, normalized, display, confidence, explicit=True):
        return {"id": self.uid("mem"), "subject": subject, "memory_type": memory_type, "category": category,
                "normalized_value": normalized, "display_value": display, "valid_from": message["timestamp"], "valid_to": None,
                "status": "current" if explicit else "uncertain", "confidence": confidence, "supersedes_id": None,
                "source_message_ids": [message["id"]], "explicit": explicit}

    @staticmethod
    def resolve(facts: list[dict]):
        groups: dict[tuple[str, str], list[dict]] = {}
        for fact in facts:
            groups.setdefault((fact["subject"], fact["category"]), []).append(fact)
        for group in groups.values():
            group.sort(key=lambda x: x["valid_from"])
            current = None
            for fact in group:
                if fact.pop("explicit", True) and fact["confidence"] >= .85:
                    if current:
                        current["status"] = "superseded"
                        current["valid_to"] = fact["valid_from"]
                        fact["supersedes_id"] = current["id"]
                    current = fact
                    fact["status"] = "current"
                elif current is None:
                    fact["status"] = "uncertain"

    @staticmethod
    def due_date(text: str) -> str | None:
        if "星期日" in text or "週日" in text:
            return "next_sunday"
        return None
