# Privacy and offline behavior

- The server binds to `127.0.0.1`; CORS permits only the local UI origin.
- There are no analytics, crash reporters, cloud APIs, remote fonts, or automatic fallbacks.
- Imported file bytes are parsed from request memory and are not retained as uploads.
- Canonical messages are stored in local SQLite and are not encrypted at rest.
- Imported message text is untrusted data and never executed as agent instructions.
- Normal logs do not print message content.
- Live Capture is off until the user starts it and chooses one window in the macOS system picker. It disables audio capture, processes frames in memory with Vision, and discards each frame; only new OCR text and minimal source metadata enter SQLite.
- OCR text that does not pass the confidence threshold is counted but not persisted. The stored timestamp is the local observation time, not a timestamp read from the chat.
- A persistent UI state and Stop control remain visible while capture runs. Stopping closes the ScreenCaptureKit stream; deleting its conversation or all data also requests Stop.
- Profiler labels and measurements contain no message text, sender name, or window title. Resource and accelerator values are marked with their measurement limitations.
- The offline test covers querying, citations, timelines, and Demo Chat after dependencies are installed.
