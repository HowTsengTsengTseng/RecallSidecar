# 聊憶 RecallSidecar — Stage I

RecallSidecar 是本機、證據優先、理解時間變化的聊天記憶引擎。它匯入 LINE 文字備份或接收 Demo Chat 訊息，將原始訊息存入 SQLite + FTS5，抽取結構化時間記憶，並以精確原文引用回答問題。若資料不足，它會回覆 `not_found`，不會靠模型常識猜答案。

本作品鎖定 ASUS UGen AI League 的 Battlefield Lightning / Everyday AI。Stage I 可在 Apple Silicon MacBook 上使用 deterministic provider 完整離線展示；Stage II 才會在 Linux + ASUS UGen300 USB 8GB 上接入 HailoRT。

## 立即 Demo

需求：Python 3.11+。第一次執行先建立環境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e backend
```

啟動：

```bash
python3 backend/run.py
```

開啟 [http://127.0.0.1:8000](http://127.0.0.1:8000)，按「載入 5,000 筆範例」。不需要 API key、模型下載或網路。
若 8000 埠已被其他本機服務使用，可用 `PORT=8001 python3 backend/run.py` 啟動並開啟 `http://127.0.0.1:8001`。

### 三分鐘展示腳本

1. 在「對話」載入 5,000 筆合成資料，顯示參與者、訊息量、日期範圍與索引狀態。
2. 在「回想」問「下週哪天沒空？」並打開引用的原始訊息。
3. 問「Alice 現在可以吃辣嗎？」；在「變更紀錄」展示不吃辣 → 可吃小辣。
4. 問「Alice 的貓叫什麼名字？」；系統應回覆 `not_found`。
5. 在 Demo Chat 輸入「生日旅行確定改去宜蘭，我已經訂好民宿了」。
6. 重新詢問生日旅行；答案更新為宜蘭，時間軸仍保留台南、花蓮。
7. 關閉 Wi-Fi 後重問一次，並展示隱私頁的 SQLite 路徑與 provider 狀態。

## 架構

```text
Buildless responsive web UI
          │ JSON / localhost only
FastAPI application (127.0.0.1)
  ├─ LINE preview + commit importer
  ├─ canonical message repository
  ├─ SQLite FTS5 lexical retrieval
  ├─ deterministic memory extractor
  ├─ temporal resolver
  ├─ evidence-only answer composer
  ├─ exact-quote citation verifier
  └─ InferenceProvider boundary
       ├─ DeterministicStubProvider (default)
       ├─ MacLocalProvider (optional Ollama API)
       └─ HailoInferenceProvider (Stage II boundary)
          │
SQLite: messages, FTS, facts, sources, commitments, jobs
```

## 功能完成度

- LINE TXT：日期、時間、sender、多行訊息、emoji、URL、貼圖與刪除標記；保留行號 locator；預覽後才 commit。
- 去重：同一 conversation 的 sender + timestamp + content 使用 SHA-256 unique hash。
- Demo Chat：與匯入共用 canonical messages、FTS 與記憶抽取流程。
- Query：偏好、時間、事件、承諾、目前狀態、變更與來源搜尋。
- 引用：speaker、timestamp、message ID、精確 quote；輸出前檢查 quote 必須存在於 raw message。
- 時序記憶：subject + category 隔離；只有明確且高信心的新敘述會 supersede 舊狀態。
- 承諾：open/done 狀態與不同來源訊息。
- 隱私：127.0.0.1、窄 CORS、無 analytics、無遠端字型、無雲端 fallback、刪除確認。
- 未辨識 LINE 記錄會以 `system` / `unknown` 類型保留並帶來源行號；日期或時間無法解析時會明確標示精度未知。
- Live Capture：macOS 上由使用者明確開啟 Apple 系統視窗選擇器，ScreenCaptureKit 僅擷取單一視窗，Vision 在本機辨識繁中與英文；不保存畫面，重複畫格不重複匯入。
- Profiler：最近 60 秒的實際 OCR、去重／匯入、記憶抽取、查詢延遲與 p50/p95；呈現取樣 CPU、RSS、每秒處理量、佇列及不可用的加速器資料。
- 查詢的語意近似訊號以本機規則、記憶標籤與中文字詞片段計分，不下載 embedding，也不呼叫 LLM；這是 deterministic retrieval signal，不等同向量語意搜尋。
- Jobs：import/index endpoint 回傳 job ID 與可查詢狀態。

## API

啟動後可查看 [http://127.0.0.1:8000/api/docs](http://127.0.0.1:8000/api/docs)。已實作：

```text
POST   /api/imports/line/preview
POST   /api/imports/line/commit
GET    /api/imports/{job_id}
GET    /api/conversations
GET    /api/conversations/{id}
DELETE /api/conversations/{id}
GET    /api/conversations/{id}/messages
POST   /api/conversations/{id}/messages
POST   /api/conversations/{id}/index
GET    /api/conversations/{id}/memories
GET    /api/conversations/{id}/changes
GET    /api/conversations/{id}/commitments
POST   /api/conversations/{id}/query
GET    /api/system/status
DELETE /api/system/data
POST   /api/demo/seed
```

## 測試

```bash
cd backend
python3 -m unittest discover -s tests -v
```

測試不下載模型，涵蓋 LINE parser、引用驗證、時間取代、不同人物隔離、引用舊訊息、去重、5,000 筆 demo、拒答及增量更新。

生成評估資料：

```bash
python3 evaluation/generate.py
python3 evaluation/evaluate.py
```

## 使用 Mac 本機模型

預設 `INFERENCE_PROVIDER=stub` 可完成全部 deterministic demo。若本機已自行安裝 Ollama 並準備 Qwen2.5 1.5B：

```bash
INFERENCE_PROVIDER=mac_local LOCAL_MODEL_NAME=qwen2.5:1.5b python3 backend/run.py
```

啟用後，新加入且帶有時間線索的計劃訊息會由本機 Qwen 抽取活動與時間，保存時仍以原始訊息為準；查詢計劃時先比對發言者和日期，再附原文引用回答。大量匯入及既有訊息的候選計劃會在背景逐步抽取，避免讓匯入等待模型處理每一筆。可用 `GET /api/conversations/{id}/plans` 查看已抽取結果；若本機模型暫時離線，未處理的舊訊息會在下次啟動或重建索引時重試。其他問答仍使用現有檢索與證據驗證流程。連線失敗不會 fallback 到雲端。

目前計劃日期支援「今天／明天／後天／本週／下週」等相對說法；更複雜日期、跨訊息指代及多輪修正尚未完整處理。`llm_used=true` 且 `llm_stage=plan_extraction` 表示模型用於抽取輸入，答案由程式依已驗證的抽取結果組成。

## 離線測試

1. 啟動服務並載入範例資料。
2. 關閉 Wi-Fi。
3. 重新提問、開啟 citation、查看變更、在 Demo Chat 新增訊息。
4. 所有核心步驟應成功。依賴安裝與模型下載不屬於此測試。

## Live Capture（macOS）

在左側開啟 Live Capture，按「開始並選擇視窗」，再於 macOS 系統選擇器選取一個合成聊天視窗。首次使用時，macOS 會要求螢幕錄製權限；允許執行後端的終端機／應用程式。頁面與頂部狀態條會顯示擷取狀態，可隨時暫停、恢復或停止。OCR 低於信心門檻的候選文字會計入不確定計數，不寫入對話。發言者未知；時間戳是觀察到文字的本機時間，並在來源資訊標明，不代表聊天原始時間。

Profiler 數值只會在實際執行後產生；目前不預設宣稱達到 2 秒目標。CPU 顯示取樣間隔內的使用率與程序累積時間，RSS 顯示程序峰值；擷取佇列由序列化處理器同步消化，沒有待處理時顯示 0。加速器讀值固定顯示 `Not available`。

## 隱私限制

- SQLite 預設路徑為 `./data/recall-sidecar.db`，可透過 `DATABASE_PATH` 修改。
- 上傳文字只存在 request memory，commit 後保存解析出的 canonical messages，不保留原始檔。
- 目前沒有 SQLCipher，因此是「local-only」，不是「encrypted-at-rest」。
- 匯入文字一律當資料處理，不當成程式或 agent 指令。
- 正常 log 不輸出 raw message；UI 刪除操作有確認步驟。

## Stage II：Linux + UGen300

`backend/app/inference/hailo.py` 已隔離 Hailo provider 介面。取得 UGen300 後，在 Linux 安裝官方 HailoRT 5.x 與 GenAI Model Zoo，使用支援的 Qwen 1B–1.7B instruct HEF，只替換 inference provider。解析、SQLite、FTS 與 citation verifier 留在 host。

目前所有 UGen300 latency、throughput、memory、power 數據均為 **TBD - measure on hardware**。不宣稱 macOS 原生支援 Hailo。

## 非目標

這不是 LINE 登入工具、訊息攔截器、關係評分器、心理診斷工具、多人 production 服務或自動回覆機器人。Repository 內沒有真實私人聊天。
