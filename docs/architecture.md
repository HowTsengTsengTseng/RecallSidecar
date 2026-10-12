# Architecture

The FastAPI app is the local process boundary. All inputs become canonical `Message` rows before retrieval or extraction. SQLite owns raw messages, FTS5, temporal facts, source mappings, commitments, jobs, and app metadata.

Temporal resolution groups by conversation, subject, and category. New facts supersede older facts only when explicit and confidence is at least 0.85. Raw messages remain immutable.

The answer service checks structured facts, commitments, then local retrieval. Retrieval combines SQLite FTS5 and a deterministic Chinese paraphrase/character-fragment signal over messages and extracted fact labels. It is a lightweight local approximation, not embedding-vector search. Every citation is rebuilt from the repository and checked for exact quote containment.

On macOS, Live Capture starts a small ScreenCaptureKit + Vision helper only after a UI action. Apple's system picker limits selection to one window; OCR candidates enter the same canonical message/index/memory path as imports and Demo Chat. Frames stay transient in memory. The API's bounded profiler stores durations and counts only.

Inference is behind a provider boundary. Stage I defaults to deterministic rules; an Ollama-compatible Mac provider exposes local health and bounded calls. The Hailo provider is an intentionally inactive Stage II boundary.
