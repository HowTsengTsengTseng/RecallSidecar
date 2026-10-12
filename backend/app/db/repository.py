from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, source_type TEXT NOT NULL,
  source_filename TEXT, timezone TEXT NOT NULL, created_at TEXT NOT NULL,
  indexing_status TEXT NOT NULL DEFAULT 'complete', memory_status TEXT NOT NULL DEFAULT 'complete'
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sender TEXT NOT NULL, timestamp TEXT NOT NULL, type TEXT NOT NULL, content TEXT NOT NULL,
  source_locator TEXT NOT NULL, content_hash TEXT NOT NULL,
  UNIQUE(conversation_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_time ON messages(conversation_id, timestamp);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  message_id UNINDEXED, conversation_id UNINDEXED, sender, content, tokenize='unicode61'
);
CREATE TABLE IF NOT EXISTS memory_facts (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  subject TEXT NOT NULL, memory_type TEXT NOT NULL, category TEXT NOT NULL,
  normalized_value TEXT NOT NULL, display_value TEXT NOT NULL,
  valid_from TEXT NOT NULL, valid_to TEXT, status TEXT NOT NULL,
  confidence REAL NOT NULL, supersedes_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_memory_lookup ON memory_facts(conversation_id, category, status);
CREATE TABLE IF NOT EXISTS memory_sources (
  memory_id TEXT NOT NULL REFERENCES memory_facts(id) ON DELETE CASCADE,
  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  PRIMARY KEY(memory_id, message_id)
);
CREATE TABLE IF NOT EXISTS commitments (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  who TEXT NOT NULL, action TEXT NOT NULL, due_date TEXT, status TEXT NOT NULL,
  source_message_id TEXT NOT NULL REFERENCES messages(id), completed_message_id TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL,
  detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def uid(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4()}"

    @staticmethod
    def hash_message(sender: str, timestamp: str, content: str) -> str:
        return hashlib.sha256(f"{sender}\x1f{timestamp}\x1f{content}".encode()).hexdigest()

    def create_conversation(self, title: str, source_type: str, source_filename: str | None, timezone: str, conversation_id: str | None = None) -> str:
        cid = conversation_id or self.uid("conv")
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO conversations VALUES(?,?,?,?,?,?,?,?)",
                (cid, title, source_type, source_filename, timezone, datetime.now().astimezone().isoformat(), "complete", "pending"),
            )
        return cid

    def insert_messages(self, conversation_id: str, messages: list[dict]) -> tuple[int, list[str]]:
        inserted, ids = 0, []
        with self.connect() as db:
            for raw in messages:
                mid = raw.get("id") or self.uid("msg")
                digest = raw.get("content_hash") or self.hash_message(raw["sender"], raw["timestamp"], raw["content"])
                cursor = db.execute(
                    "INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?,?)",
                    (mid, conversation_id, raw["sender"], raw["timestamp"], raw.get("type", "text"), raw["content"], json.dumps(raw.get("source_locator", {}), ensure_ascii=False), digest),
                )
                if cursor.rowcount:
                    inserted += 1
                    ids.append(mid)
                    db.execute("INSERT INTO messages_fts VALUES(?,?,?,?)", (mid, conversation_id, raw["sender"], raw["content"]))
            db.execute("UPDATE app_meta SET value=? WHERE key='last_indexed'", (datetime.now().astimezone().isoformat(),))
            db.execute("INSERT OR IGNORE INTO app_meta VALUES('last_indexed',?)", (datetime.now().astimezone().isoformat(),))
        return inserted, ids

    def list_conversations(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""
              SELECT c.*, COUNT(m.id) message_count, COUNT(DISTINCT m.sender) participant_count,
                     MIN(m.timestamp) date_start, MAX(m.timestamp) date_end
              FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id
              GROUP BY c.id ORDER BY c.created_at DESC
            """).fetchall()
        return [dict(r) for r in rows]

    def get_conversation(self, conversation_id: str) -> dict | None:
        return next((x for x in self.list_conversations() if x["id"] == conversation_id), None)

    def find_import_conversation(self, title: str, source_filename: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT id FROM conversations WHERE source_type='line_txt' AND title=? AND source_filename=? ORDER BY created_at LIMIT 1",
                (title, source_filename),
            ).fetchone()
        return self.get_conversation(row[0]) if row else None

    def messages(self, conversation_id: str, limit: int = 100, before: str | None = None, around: str | None = None) -> list[dict]:
        with self.connect() as db:
            if around:
                target = db.execute("SELECT timestamp FROM messages WHERE id=? AND conversation_id=?", (around, conversation_id)).fetchone()
                if target:
                    before_rows = db.execute("SELECT * FROM messages WHERE conversation_id=? AND timestamp<=? ORDER BY timestamp DESC LIMIT ?", (conversation_id, target[0], limit // 2 + 1)).fetchall()
                    after_rows = db.execute("SELECT * FROM messages WHERE conversation_id=? AND timestamp>? ORDER BY timestamp LIMIT ?", (conversation_id, target[0], limit // 2)).fetchall()
                    rows = list(reversed(before_rows)) + list(after_rows)
                else:
                    rows = []
            elif before:
                rows = list(reversed(db.execute("SELECT * FROM messages WHERE conversation_id=? AND timestamp<? ORDER BY timestamp DESC LIMIT ?", (conversation_id, before, limit)).fetchall()))
            else:
                rows = list(reversed(db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY timestamp DESC LIMIT ?", (conversation_id, limit)).fetchall()))
        return [self._message(r) for r in rows]

    def message(self, message_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return self._message(row) if row else None

    @staticmethod
    def _message(row) -> dict:
        value = dict(row)
        value["source_locator"] = json.loads(value["source_locator"])
        return value

    def replace_analysis(self, conversation_id: str, facts: list[dict], commitments: list[dict]):
        with self.connect() as db:
            db.execute("DELETE FROM commitments WHERE conversation_id=?", (conversation_id,))
            db.execute("DELETE FROM memory_facts WHERE conversation_id=?", (conversation_id,))
            for f in facts:
                db.execute("INSERT INTO memory_facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                    f["id"], conversation_id, f["subject"], f["memory_type"], f["category"], f["normalized_value"], f["display_value"],
                    f["valid_from"], f.get("valid_to"), f["status"], f["confidence"], f.get("supersedes_id")))
                for mid in f["source_message_ids"]:
                    db.execute("INSERT INTO memory_sources VALUES(?,?)", (f["id"], mid))
            for c in commitments:
                db.execute("INSERT INTO commitments VALUES(?,?,?,?,?,?,?,?)", (
                    c["id"], conversation_id, c["who"], c["action"], c.get("due_date"), c["status"], c["source_message_id"], c.get("completed_message_id")))
            db.execute("UPDATE conversations SET memory_status='complete', indexing_status='complete' WHERE id=?", (conversation_id,))

    def facts(self, conversation_id: str, category: str | None = None) -> list[dict]:
        query = """SELECT f.*, GROUP_CONCAT(s.message_id) source_ids FROM memory_facts f
                   LEFT JOIN memory_sources s ON s.memory_id=f.id WHERE f.conversation_id=?"""
        params: list = [conversation_id]
        if category:
            query += " AND f.category=?"; params.append(category)
        query += " GROUP BY f.id ORDER BY f.valid_from"
        with self.connect() as db: rows = db.execute(query, params).fetchall()
        result=[]
        for r in rows:
            d=dict(r);d["source_message_ids"]=(d.pop("source_ids") or "").split(",");result.append(d)
        return result

    def commitments(self, conversation_id: str) -> list[dict]:
        with self.connect() as db: rows=db.execute("SELECT * FROM commitments WHERE conversation_id=? ORDER BY rowid",(conversation_id,)).fetchall()
        return [dict(r) for r in rows]

    def fts_search(self, conversation_id: str, query: str, limit: int = 10) -> list[dict]:
        terms = [x for x in query.replace("？", " ").replace("?", " ").split() if x]
        if not terms: return []
        expression = " OR ".join(f'"{x.replace(chr(34), "")}"' for x in terms)
        try:
            with self.connect() as db:
                ids=[r[0] for r in db.execute("SELECT message_id FROM messages_fts WHERE conversation_id=? AND messages_fts MATCH ? ORDER BY bm25(messages_fts) LIMIT ?",(conversation_id,expression,limit)).fetchall()]
            return [m for i in ids if (m:=self.message(i))]
        except sqlite3.OperationalError:
            return []

    def semantic_search(self, conversation_id: str, query: str, limit: int = 10) -> list[dict]:
        """Small local semantic signal: normalize common Chinese paraphrases and rank facts + text.

        This deliberately uses no model or network. It is a lexical approximation and is
        exposed as one retrieval signal alongside FTS, not as embedding similarity.
        """
        aliases = {
            "目前": ["現在", "目前", "最近", "最後", "現階段"],
            "偏好": ["喜歡", "不喜歡", "愛吃", "不吃", "可以吃", "接受"],
            "行程": ["沒空", "不能", "有空", "哪天", "星期", "時間"],
            "承諾": ["答應", "會", "要", "訂", "買", "完成"],
            "地點": ["去哪", "哪裡", "目的地", "旅行", "生日", "台南", "花蓮", "宜蘭"],
            "來源": ["原文", "訊息", "提到", "說過", "哪一句"],
        }
        expanded = set(query.replace("？", " ").replace("?", " ").split())
        for group in aliases.values():
            if any(term in query for term in group):
                expanded.update(group)
        terms = [term for term in expanded if len(term) > 1]
        candidates: dict[str, tuple[int, dict]] = {}
        useful_terms = terms + [query[i:i + 2] for i in range(len(query) - 1) if "\u4e00" <= query[i] <= "\u9fff"]
        for message in self.messages(conversation_id, limit=100000):
            text = f"{message['sender']} {message['content']}"
            score = sum(text.count(t) for t in useful_terms if len(t) > 1)
            if score:
                candidates[message["id"]] = (score, message)
        for fact in self.facts(conversation_id):
            text = f"{fact['subject']} {fact['category']} {fact['display_value']} {fact['normalized_value']}"
            if any(term in text for term in terms):
                for mid in fact["source_message_ids"]:
                    if message := self.message(mid):
                        score = sum(text.count(t) for t in terms) + 2
                        candidates[message["id"]] = (max(score, candidates.get(message["id"], (0, {}))[0]), message)
        return [item[1] for item in sorted(candidates.values(), key=lambda pair: pair[0], reverse=True)[:limit]]

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.connect() as db:
            ids=[r[0] for r in db.execute("SELECT id FROM messages WHERE conversation_id=?",(conversation_id,)).fetchall()]
            if ids: db.executemany("DELETE FROM messages_fts WHERE message_id=?", [(x,) for x in ids])
            cur=db.execute("DELETE FROM conversations WHERE id=?",(conversation_id,))
        return bool(cur.rowcount)

    def delete_all(self):
        with self.connect() as db:
            db.execute("DELETE FROM messages_fts");db.execute("DELETE FROM conversations");db.execute("DELETE FROM jobs");db.execute("DELETE FROM app_meta")

    def system_counts(self) -> dict:
        with self.connect() as db:
            conversations=db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            messages=db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            row=db.execute("SELECT value FROM app_meta WHERE key='last_indexed'").fetchone()
        return {"conversation_count":conversations,"message_count":messages,"last_indexed":row[0] if row else None}

    def create_job(self, kind: str, status="completed", detail: dict | None = None) -> str:
        jid=self.uid("job");now=datetime.now().astimezone().isoformat()
        with self.connect() as db: db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",(jid,kind,status,100 if status=="completed" else 0,json.dumps(detail or {},ensure_ascii=False),now,now))
        return jid

    def job(self, job_id: str) -> dict | None:
        with self.connect() as db: row=db.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not row:return None
        d=dict(row);d["detail"]=json.loads(d["detail"] or "{}");return d
