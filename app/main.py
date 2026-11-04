"""HTTP biên của AI service (FastAPI, cổng 8020).

FE gọi đây, đây gọi LiveTalking. Đây KHÔNG gọi BE và không lưu phiên phỏng vấn: BE (spec 012)
mới là nơi lưu, còn service này chỉ giữ transcript trong bộ nhớ cho tới khi hết hạn.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.avatar import AvatarClient, AvatarError
from app.config import Settings
from app.llm import build_generator
from app.sessions import Orchestrator, SessionNotFound, SessionStore, TurnConflict
from app.stt import Transcriber

log = logging.getLogger("ai")

# Quy tắc "kiểm tra loại và kích thước tệp": 10 phút nói ~ 1 MB opus, 10 MB là dư rất nhiều
MAX_AUDIO_BYTES = 10 * 1024 * 1024
ALLOWED_AUDIO_PREFIX = "audio/"


class OfferIn(BaseModel):
    sdp: str = Field(min_length=20)
    type: str = "offer"


class SessionIn(BaseModel):
    jobTitle: str = ""
    jdText: str = ""
    avatarSessionId: str = Field(min_length=1)


class QuestionIn(BaseModel):
    questionIndex: Optional[int] = None
    speak: bool = True


class AnswerIn(BaseModel):
    """Cùng tên field với SubmitAnswerRequest của BE để FE dùng một kiểu dữ liệu."""
    questionText: str = ""
    answerText: str = ""
    questionIndex: Optional[int] = None
    durationSec: Optional[int] = None
    confirm: Optional[bool] = True


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def create_app(settings: Settings) -> FastAPI:
    store = SessionStore(settings.session_ttl_min)
    avatar = AvatarClient(settings.avatar_server, settings.avatar_id)
    stt = Transcriber(settings.stt_model, settings.stt_device, settings.stt_compute)
    orch = Orchestrator(settings, store, build_generator(settings), stt, avatar)

    app = FastAPI(title="HireMind AI service", version="1.0")
    app.add_middleware(CORSMiddleware, allow_origins=[settings.allowed_origin],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.on_event("startup")
    async def _startup() -> None:
        # Tải whisper lúc khởi động để câu trả lời đầu không phải chờ; nếu mô hình hỏng thì service
        # vẫn chạy — người dùng gõ chữ vẫn phỏng vấn được, log sẽ nói rõ vì sao STT chưa sẵn sàng.
        async def _warm() -> None:
            try:
                await asyncio.to_thread(stt.warmup)
                log.info("STT ready: %s/%s/%s", settings.stt_model, settings.stt_device,
                         settings.stt_compute)
            except Exception as e:  # noqa: BLE001
                log.warning("STT warmup thất bại: %s", e)

        asyncio.create_task(_warm())

    def http(error: Exception) -> HTTPException:
        if isinstance(error, SessionNotFound):
            return HTTPException(404, str(error))
        if isinstance(error, TurnConflict):
            return HTTPException(400, str(error))
        if isinstance(error, AvatarError):
            log.warning("Avatar lỗi: %s", error)
            return HTTPException(502, "Máy chủ avatar không phản hồi, thử lại sau")
        if isinstance(error, ValueError):
            return HTTPException(400, str(error))
        log.exception("Lỗi không mong muốn")
        return HTTPException(500, "Lỗi trong của AI service")

    def session_or_404(sid: str):
        try:
            return store.get(sid)
        except SessionNotFound as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/health")
    async def health() -> dict:
        try:
            sessions = len(await avatar.active_sessions())
        except AvatarError:
            sessions = -1  # avatar không với tới được — FE phải biết trước khi mở phiên
        return {"status": "ok", "avatarServer": settings.avatar_server, "avatarId": settings.avatar_id,
                "avatarSessions": sessions, "sttModel": settings.stt_model,
                "llmProvider": "openai" if settings.llm_ready() else "template",
                "openSessions": store.count(), "maxTurns": settings.max_turns,
                "rubricVersion": settings.rubric_version}

    @app.post("/api/v1/ai/avatar/offer")
    async def offer(payload: OfferIn) -> dict:
        """Chuyển tiếp SDP của trình duyệt sang LiveTalking, nhúng avatar_id từ biến môi trường."""
        try:
            return await avatar.offer(payload.sdp, payload.type)
        except Exception as e:  # noqa: BLE001
            raise http(e) from e

    @app.post("/api/v1/ai/session")
    async def create_session(payload: SessionIn) -> dict:
        session = store.create(payload.jobTitle, payload.jdText, payload.avatarSessionId,
                               settings.max_turns)
        log.info("Mở phiên AI %s (avatar %s)", session.id, session.avatar_session_id)
        return {"sessionid": session.id, "maxTurns": session.max_turns,
                "rubricVersion": settings.rubric_version}

    @app.get("/api/v1/ai/session/{sid}/question")
    async def get_question(sid: str, questionIndex: Optional[int] = None, speak: bool = True) -> dict:
        try:
            return await orch.question(sid, questionIndex, speak)
        except Exception as e:  # noqa: BLE001
            raise http(e) from e

    @app.post("/api/v1/ai/session/{sid}/answer")
    async def answer_text(sid: str, payload: AnswerIn) -> dict:
        """Gõ tay hoặc dán chữ (đường lùi khi micro bị từ chối)."""
        try:
            return await orch.answer(sid, text=payload.answerText, index=payload.questionIndex,
                                     duration_sec=payload.durationSec,
                                     confirm=payload.confirm is not False)
        except Exception as e:  # noqa: BLE001
            raise http(e) from e

    @app.post("/api/v1/ai/session/{sid}/answer/audio")
    async def answer_audio(sid: str, file: UploadFile = File(...),
                           questionIndex: Optional[int] = Form(None),
                           durationSec: Optional[int] = Form(None),
                           confirm: bool = Form(True)) -> dict:
        kind = (file.content_type or "").split(";")[0]
        if not kind.startswith(ALLOWED_AUDIO_PREFIX):
            raise HTTPException(400, f"Chỉ nhận file âm thanh, nhận phải {kind or 'không rõ loại'}")
        audio = await file.read()
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(400, "File âm thanh quá 10 MB, hãy ghi âm ngắn hơn")
        log.info("Nhận âm thanh %s bytes cho phiên %s", len(audio), sid)  # chỉ số bytes, không ghi nội dung
        try:
            return await orch.answer(sid, audio=audio, index=questionIndex,
                                     duration_sec=durationSec, confirm=confirm)
        except Exception as e:  # noqa: BLE001
            raise http(e) from e

    @app.post("/api/v1/ai/session/{sid}/speak")
    async def speak(sid: str, payload: SpeakIn) -> dict:
        """Cho FE bảo avatar nhắc lại/nói một câu cố định (ví dụ hướng dẫn trước khi ghi âm)."""
        session = session_or_404(sid)
        try:
            await orch.speak(session, payload.text)
            return {"sessionid": sid, "chars": len(payload.text)}
        except Exception as e:  # noqa: BLE001
            raise http(e) from e

    @app.get("/api/v1/ai/session/{sid}/speaking")
    async def speaking(sid: str) -> dict:
        session = session_or_404(sid)
        try:
            return {"speaking": await avatar.speaking(session.avatar_session_id)}
        except Exception as e:  # noqa: BLE001
            raise http(e) from e

    @app.post("/api/v1/ai/session/{sid}/interrupt")
    async def interrupt(sid: str) -> dict:
        session = session_or_404(sid)
        try:
            await avatar.interrupt(session.avatar_session_id)
            return {"sessionid": sid, "interrupted": True}
        except Exception as e:  # noqa: BLE001
            raise http(e) from e

    @app.get("/api/v1/ai/session/{sid}/transcript")
    async def transcript(sid: str) -> dict:
        session = session_or_404(sid)
        return {"sessionid": sid, "transcript": session.transcript()}

    @app.post("/api/v1/ai/session/{sid}/evaluate")
    async def evaluate(sid: str) -> dict:
        try:
            result = await orch.evaluate(sid)
            log.info("Đã chấm rubric phiên %s sau %s lượt", sid, result["turns"])
            return result
        except Exception as e:  # noqa: BLE001
            raise http(e) from e

    @app.delete("/api/v1/ai/session/{sid}")
    async def close_session(sid: str) -> dict:
        """Xóa transcript ngay khi FE báo kết thúc — mặc định là hết hạn, đây là đường xóa chủ động."""
        store.delete(sid)
        return {"sessionid": sid, "deleted": True}

    return app
