from __future__ import annotations

from datetime import datetime, timedelta
import random


FACTS = {
    1023: ("Alice", "2026-03-03T19:42:00+08:00", "我最近完全不吃辣，連小辣都不行。"),
    2139: ("Alice", "2026-05-12T12:06:00+08:00", "下週三下午我沒空，要去辦事情。"),
    2780: ("Alice", "2026-06-18T20:15:00+08:00", "生日旅行也許去台南，好像不錯。"),
    3501: ("小宇", "2026-07-21T18:05:00+08:00", "我答應星期日前把晚餐餐廳訂好。"),
    4216: ("Alice", "2026-08-14T21:32:00+08:00", "我現在可以吃一點小辣了，但中辣還是不行。"),
    4549: ("Alice", "2026-09-02T10:10:00+08:00", "生日旅行確定改去花蓮，我已經訂好車票了。"),
    4699: ("小宇", "2026-09-05T16:20:00+08:00", "晚餐餐廳已經訂好了，星期日晚上六點。"),
    4819: ("Alice", "2026-09-12T09:10:00+08:00", "上次週年紀念我們去了淡水，傍晚還搭了渡船。"),
}


def generate_messages(count: int = 5000) -> list[dict]:
    random.seed(42)
    snippets = ["今天工作好多，晚點再聊", "剛剛看到一間很可愛的店", "午餐吃什麼好？", "明天記得帶雨傘", "這張貼圖也太好笑了", "我到家了", "週末可能會下雨", "那家咖啡店人很多", "收到，等等回你", "先去忙一下", "你有看到那部電影嗎", "晚安，明天見"]
    start = datetime.fromisoformat("2026-01-01T08:00:00+08:00")
    result=[]
    for i in range(count):
        sender = "小宇" if i % 2 else "Alice"
        timestamp = (start + timedelta(minutes=i * 70)).isoformat()
        content = random.choice(snippets)
        if i in FACTS: sender, timestamp, content = FACTS[i]
        result.append({"id": f"msg-{i+1:04d}", "sender": sender, "timestamp": timestamp, "type": "text", "content": content,
                       "source_locator": {"filename": "synthetic-line-chat.txt", "line_start": i + 4, "line_end": i + 4}})
    return result
