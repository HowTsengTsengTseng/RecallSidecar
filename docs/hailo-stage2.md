# Stage II: UGen300 integration plan

Target: Linux host with ASUS UGen300 USB 8GB / Hailo-10H.

Replace only `HailoInferenceProvider` using HailoRT 5.x GenAI API and a supported Qwen 1B–1.7B model. Keep parsing, SQLite, FTS5, metadata filters, temporal resolution, and citation verification on the host CPU.

Required physical-hardware measurements: time to first token, end-to-end latency, extraction throughput, host CPU utilization with and without acceleration, and power only when a reliable measurement is available.

All values remain `TBD - measure on hardware`. Stage I makes no native macOS Hailo claim.

