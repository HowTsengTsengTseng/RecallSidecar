from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import re
import hashlib


DATE_RE = re.compile(r"^(\d{4})[./年](\d{1,2})[./月](\d{1,2})日?(?:\s*[（(][^）)]*[）)])?$")
MESSAGE_RE = re.compile(r"^(\d{1,2}):(\d{2})(?:\s|\t)+([^\t]+?)(?:\t|\s{1,})(.*)$")
TITLE_PATTERNS = [
    re.compile(r"\[LINE\]\s*(.+?)(?:的聊天記錄|聊天記錄)$"),
    re.compile(r"Chat history with\s+(.+)", re.I),
]


class LineTxtImporter:
    def __init__(self, timezone: str = "Asia/Taipei"):
        self.timezone = timezone

    def parse(self, content: str, filename: str = "line-chat.txt") -> dict:
        lines = content.lstrip("\ufeff").splitlines()
        title = filename.rsplit(".", 1)[0]
        for line in lines[:8]:
            for pattern in TITLE_PATTERNS:
                if match := pattern.search(line.strip()):
                    title = match.group(1).strip()
                    break
        current_date = None
        messages: list[dict] = []
        rejected: list[dict] = []
        unknown_messages: list[dict] = []
        warnings: list[str] = []
        last: dict | None = None

        for index, raw in enumerate(lines, 1):
            line = raw.rstrip("\r")
            if match := DATE_RE.match(line.strip()):
                current_date = tuple(map(int, match.groups()))
                last = None
                continue
            if current_date and (match := MESSAGE_RE.match(line)):
                hour, minute, sender, text = match.groups()
                dt = datetime(*current_date, int(hour), int(minute), tzinfo=ZoneInfo(self.timezone))
                last = {
                    "sender": sender.strip(),
                    "timestamp": dt.isoformat(),
                    "type": self._type(text),
                    "content": text,
                    "source_locator": {"filename": filename, "line_start": index, "line_end": index},
                }
                messages.append(last)
                continue
            if last is not None and line.strip() and not self._system_record(line):
                last["content"] += "\n" + line
                last["source_locator"]["line_end"] = index
                continue
            if line.strip() and not self._header(line):
                rejected.append({"line": index, "text": line, "reason": "unrecognized_record"})
                date_prefix = datetime(*current_date).date().isoformat() if current_date else None
                unknown_messages.append({
                    "sender": "unknown", "timestamp": date_prefix or "",
                    "type": "system" if self._system_record(line) else "unknown", "content": line,
                    "source_locator": {"filename": filename, "line_start": index, "line_end": index,
                                       "timestamp_precision": "day" if current_date else "unknown"},
                    "content_hash": hashlib.sha256(f"{filename}\x1funknown\x1f{index}\x1f{line}".encode("utf-8")).hexdigest(),
                })

        if rejected:
            warnings.append(f"{len(rejected)} records could not be assigned a timestamp; they will be stored as system/unknown messages on commit.")
        if not messages:
            warnings.append("No timestamped messages were recognized.")
        return {
            "title": title, "source_filename": filename, "timezone": self.timezone,
            "messages": messages, "unknown_messages": unknown_messages,
            "participants": sorted({m["sender"] for m in messages}),
            "rejected": rejected, "warnings": warnings,
            "date_start": messages[0]["timestamp"] if messages else None,
            "date_end": messages[-1]["timestamp"] if messages else None,
        }

    @staticmethod
    def _header(line: str) -> bool:
        value = line.strip().lower()
        return not value or value.startswith("[line]") or value.startswith("儲存日期") or value.startswith("saved on")

    @staticmethod
    def _system_record(line: str) -> bool:
        value = line.strip()
        markers = ("已加入群組", "加入了群組", "離開群組", "退出群組", "更改群組名稱", "建立群組",
                   "收回了一則訊息", "已收回訊息", "unsent a message", "joined the group", "left the group")
        return any(marker in value.lower() for marker in markers)

    @staticmethod
    def _type(text: str) -> str:
        if re.fullmatch(r"\[(?:貼圖|圖片|影片|檔案|sticker|photo|video)\]", text.strip(), re.I):
            return "attachment"
        if any(token in text for token in ("已收回訊息", "收回了一則訊息", "unsent a message")):
            return "deleted"
        return "text"
