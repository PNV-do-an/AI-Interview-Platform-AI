"""Cấu hình AI service — mọi thứ từ biến môi trường, không có khóa nào trong mã nguồn."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(key: str, default: str = "") -> str:
    value = os.environ.get(key, default)
    return value.strip()


@dataclass(frozen=True)
class Settings:
    # LiveTalking (repo vendored) — avatar + WebRTC
    avatar_server: str
    avatar_id: str
    # STT
    stt_model: str
    stt_device: str
    stt_compute: str
    # LLM: "template" = không cần khóa, chạy được ngay; "openai" = OpenAI-compatible qua env
    llm_provider: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    # Ràng buộc nghiệp vụ, khớp trần 40 lượt của BE spec 012
    max_turns: int
    rubric_version: str
    # Phiên chỉ nằm trong bộ nhớ — hết hạn là xóa, không để transcript tồn tại vô hạn
    session_ttl_min: int
    listen_host: str
    listen_port: int
    allowed_origin: str

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            avatar_server=_env("AI_AVATAR_SERVER", "http://127.0.0.1:8010"),
            avatar_id=_env("AI_AVATAR_ID", "vn_interviewer_v1"),
            # small + int8 trên CPU: đo 26/10 hết 4.5..5.0s cho câu 6.0s khi máy không chạy
            # avatar; GPU đang bị LiveTalking giữ 3716/4096 MiB nên STT không còn chỗ.
            stt_model=_env("AI_STT_MODEL", "small"),
            stt_device=_env("AI_STT_DEVICE", "cpu"),
            stt_compute=_env("AI_STT_COMPUTE", "int8"),
            llm_provider=_env("AI_LLM_PROVIDER", "template").lower(),
            llm_base_url=_env("AI_LLM_BASE_URL"),
            llm_api_key=_env("AI_LLM_API_KEY"),
            llm_model=_env("AI_LLM_MODEL"),
            max_turns=int(_env("AI_MAX_TURNS", "40")),
            rubric_version=_env("AI_RUBRIC_VERSION", "2026-10-v1"),
            session_ttl_min=int(_env("AI_SESSION_TTL_MIN", "180")),
            listen_host=_env("AI_HOST", "0.0.0.0"),
            listen_port=int(_env("AI_PORT", "8020")),
            allowed_origin=_env("AI_ALLOWED_ORIGIN", "http://localhost:3000"),
        )

    def llm_ready(self) -> bool:
        return self.llm_provider == "openai" and bool(self.llm_base_url and self.llm_model)
