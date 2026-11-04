"""STT: faster-whisper trên CPU.

GPU đang bị LiveTalking giữ 3716/4096 MiB nên không còn chỗ cho mô hình âm thanh;
small + int8 trên CPU đo 26/10 hết 0.85..1.05 giây cho mỗi giây nói, đủ cho buổi phỏng vấn
một người một máy. initial_prompt chứa từ điển ngành là thứ giữ được "backend", "Spring Boot",
"React" — không có thì whisper viết thành "bắc kèn", "stringbook", "khích" (đo 26/10).
"""
from __future__ import annotations

import threading

import numpy as np

DOMAIN_PROMPT = (
    "Đây là buổi phỏng vấn kỹ thuật phần mềm bằng tiếng Việt về Java, Spring Boot, React, "
    "WebRTC, cơ sở dữ liệu, PostgreSQL, Docker, Kubernetes, backend, frontend, API, REST, "
    "microservice, hiệu năng, chỉ mục, giao dịch."
)


class Transcriber:
    def __init__(self, model_size: str, device: str, compute_type: str) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_size, device=self.device,
                                       compute_type=self.compute_type)
        return self._model

    def warmup(self) -> None:
        """Tải mô hình một lần lúc khởi động, để câu trả lời đầu tiên không phải chờ 2 giây."""
        with self._lock:
            self._get_model()

    def transcribe(self, samples: np.ndarray) -> tuple[str, float]:
        """(chữ, số giây âm thanh). Blocking — gọi qua asyncio.to_thread."""
        with self._lock:
            model = self._get_model()
            segments, info = model.transcribe(
                samples, language="vi", vad_filter=True, initial_prompt=DOMAIN_PROMPT)
            text = "".join(s.text for s in segments).strip()
        return text, float(info.duration or 0.0)
