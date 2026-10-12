from __future__ import annotations

from collections import deque
from datetime import datetime
import resource
import sys
import statistics
import threading
import time


class PipelineProfiler:
    """Bounded, content-free measurements for recent pipeline work."""
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._events: deque[tuple[float, str, float]] = deque(maxlen=5000)
        self._counters = {"messages_ingested": 0, "duplicates_dropped": 0, "ocr_frames": 0,
                          "new_text_detected": 0, "uncertain_detections": 0}
        self.paused = False
        self._last_cpu_sample: tuple[float, float] | None = None

    def record(self, stage: str, duration_ms: float, counter: str | None = None):
        now = time.monotonic()
        with self._lock:
            if self.paused:
                return
            self._events.append((now, stage, max(0, duration_ms)))
            if counter:
                self._counters[counter] = self._counters.get(counter, 0) + 1
            cutoff = now - self.window_seconds
            while self._events and self._events[0][0] < cutoff:
                self._events.popleft()

    def reset(self):
        with self._lock:
            self._events.clear()
            for key in self._counters:
                self._counters[key] = 0

    def snapshot(self, capture: dict | None = None):
        with self._lock:
            cutoff = time.monotonic() - self.window_seconds
            events = [(stage, duration) for stamp, stage, duration in self._events if stamp >= cutoff]
            counters = dict(self._counters)
            paused = self.paused
        timings = {}
        for stage in {name for name, _ in events}:
            values = [v for name, v in events if name == stage]
            ordered = sorted(values)
            timings[stage] = {"count": len(values), "p50_ms": round(statistics.median(values), 2),
                              "p95_ms": round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 2)}
        usage = resource.getrusage(resource.RUSAGE_SELF)
        wall = time.monotonic()
        cpu = usage.ru_utime + usage.ru_stime
        cpu_percent = None
        if self._last_cpu_sample:
            prev_wall, prev_cpu = self._last_cpu_sample
            if wall > prev_wall: cpu_percent = round((cpu - prev_cpu) / (wall - prev_wall) * 100, 1)
        self._last_cpu_sample = (wall, cpu)
        observed = sum(1 for name, _ in events if name == "ocr")
        ingest_events = sum(1 for name, _ in events if name == "capture_detection")
        return {"window_seconds": self.window_seconds, "sampling_paused": paused, "counters": counters,
                "timings": timings, "throughput": {"ocr_passes_per_second": round(observed / self.window_seconds, 2),
                "new_text_detections_per_second": round(ingest_events / self.window_seconds, 2),
                "ocr_queue_depth": 0, "extraction_queue_depth": 0,
                "oldest_queue_item_age_seconds": 0},
                "host": {"cpu_percent_since_last_sample": cpu_percent, "cpu_user_seconds": round(usage.ru_utime, 3),
                "cpu_system_seconds": round(usage.ru_stime, 3), "resident_memory_mb": round(usage.ru_maxrss / (1024*1024 if sys.platform == "darwin" else 1024), 2),
                "memory_note": "process peak RSS; sampled on request"},
                "accelerator": {"status": "Not available"}, "capture": capture or {"status": "not_started"},
                "captured_at": datetime.now().astimezone().isoformat()}
