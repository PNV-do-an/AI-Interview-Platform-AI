"""Phiên hội thoại trong bộ nhớ + điều phối một lượt (câu hỏi -> avatar nói -> STT -> câu kế).

Ba ràng buộc lấy từ quy trình dữ liệu của đề bài:
  - Không ghi âm ra đĩa: byte âm thanh đi qua `submit_answer` chỉ tồn tại trong một lần gọi,
    sau khi thành chữ là bị bỏ; thứ ở lại duy nhất là text.
  - Hết hạn là xóa: session tự nguội sau AI_SESSION_TTL_MIN phút không dùng, và FE có thể xóa
    sớm bằng POST /session/{id}/end. Điểm nằm ở BE (spec 012), mất ở đây không mất gì.
  - Một lượt một lúc: khóa theo session, để hai request trả lời cùng lượt không ghi đè nhau.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.audio import decode_any, wav_to_float32
from app.avatar import AvatarClient
from app.llm import Turn, build_generator
from app.stt import Transcriber


class SessionNotFound(KeyError):
    pass


class TurnConflict(ValueError):
    """Lượt không hợp lệ theo đúng nghĩa mà BE spec 012 chặn: vượt trần, ghi lại lượt đã chốt."""


@dataclass
class Session:
    id: str
    job_title: str
    jd_text: str
    avatar_session_id: str
    max_turns: int
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    next_index: int = 0
    questions: dict[int, str] = field(default_factory=dict)
    turns: dict[int, Turn] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        self.last_used = time.time()

    def history(self) -> list[Turn]:
        return [self.turns[i] for i in sorted(self.turns)]

    def transcript(self) -> list[dict]:
        out = []
        for i in sorted(self.questions):
            t = self.turns.get(i)
            out.append({"index": i, "questionText": self.questions[i],
                        "answerText": t.answer if t else None,
                        "answeredAt": t.answered_at if t else None})
        return out


class SessionStore:
    def __init__(self, ttl_min: int) -> None:
        self.ttl_sec = ttl_min * 60.0
        self._sessions: dict[str, Session] = {}

    def create(self, job_title: str, jd_text: str, avatar_session_id: str, max_turns: int) -> Session:
        self.sweep()
        session = Session(id=str(uuid.uuid4()), job_title=job_title, jd_text=jd_text,
                          avatar_session_id=avatar_session_id, max_turns=max_turns)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(f"Phiên {session_id} không tồn tại hoặc đã hết hạn")
        session.touch()
        return session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def sweep(self) -> int:
        """Bỏ session quá hạn; trả số dòng đã xóa để log khi cần điều tra."""
        now = time.time()
        stale = [k for k, s in self._sessions.items() if now - s.last_used > self.ttl_sec]
        for k in stale:
            self._sessions.pop(k, None)
        return len(stale)

    def count(self) -> int:
        return len(self._sessions)


class Orchestrator:
    """Ghép sinh câu hỏi (llm), giọng nói + máy miệng (avatar), và chữ hóa âm thanh (stt)."""

    def __init__(self, settings, store: SessionStore, generator, stt: Transcriber,
                 avatar: AvatarClient) -> None:
        self.settings = settings
        self.store = store
        self.generator = generator
        self.stt = stt
        self.avatar = avatar

    async def speak(self, session: Session, text: str) -> None:
        """Giao câu hỏi cho TTS của tiến trình avatar, không chờ nó phát tiếng.

        Đo 26/10 (scripts/p1_tts_spread.py, 7 câu): `/human` trả code 0 ngay, còn âm thanh xuất
        hiện sau 2.78..19.62s (trung vị 5.73s) và 1/7 câu không có tiếng nào — EdgeTTS gọi qua
        mạng, lỗi NoAudioReceived chỉ nằm trong log của LiveTalking. Chờ ở đây kéo phản hồi
        thành hàng chục giây mà vẫn không đảm bảo avatar nói. Vì vậy hợp đồng với ứng viên là
        chữ: FE hiện phụ đề từ questionText ngay, poll /speaking để biết khi nào mở micro, và
        bấm /speak đọc lại khi avatar im lặng.
        """
        await self.avatar.speak_text(session.avatar_session_id, text)

    async def _question(self, session: Session, index: Optional[int] = None,
                        speak: bool = True) -> dict:
        """Không tự lấy khóa — `answer` gọi lại khi đang giữ khóa. Đã sinh rồi thì trả lại nguyên câu."""
        i = session.next_index if index is None else index
        if i < 0 or i > session.next_index:
            raise TurnConflict("Không hỏi được vào lượt chưa tới, hãy trả lời lượt hiện tại")
        if i >= session.max_turns:
            raise TurnConflict(f"Phiên đã đạt số lượt tối đa ({session.max_turns}), hãy kết thúc")
        text = session.questions.get(i)
        if text is None:
            text = self.generator.next_question(session.job_title, session.jd_text,
                                                session.history(), i)
            if text is None:
                return {"sessionid": session.id, "index": i, "questionText": None, "done": True}
            session.questions[i] = text
        if speak:
            await self.speak(session, text)
        session.touch()
        return {"sessionid": session.id, "index": i, "questionText": text, "done": False}

    async def question(self, session_id: str, index: Optional[int] = None,
                       speak: bool = True) -> dict:
        session = self.store.get(session_id)
        async with session.lock:
            return await self._question(session, index, speak)

    async def answer(self, session_id: str, *, text: Optional[str] = None,
                     audio: Optional[bytes] = None, index: Optional[int] = None,
                     duration_sec: Optional[int] = None, confirm: bool = True,
                     ask_next: bool = True, speak_next: bool = True) -> dict:
        """Ghi câu trả lời (chữ hoặc âm thanh) đúng lượt rồi sinh lượt kế; âm thanh không được giữ lại."""
        session = self.store.get(session_id)
        async with session.lock:
            i = session.next_index if index is None else index
            if i < 0 or i > session.next_index:
                raise TurnConflict("Không ghi được vào lượt chưa tới, hãy trả lời lượt hiện tại")
            if i >= session.max_turns:
                raise TurnConflict(f"Phiên đã đạt số lượt tối đa ({session.max_turns}), hãy kết thúc")
            if i in session.turns and session.turns[i].confirmed:
                raise TurnConflict("Lượt này đã được chốt")
            if session.questions.get(i) is None:
                raise TurnConflict("Lượt này chưa có câu hỏi, hãy lấy câu hỏi trước")

            answer_text = (text or "").strip()
            audio_seconds = 0.0
            if not answer_text and audio is not None:
                wav = decode_any(audio)
                samples, _rate = wav_to_float32(wav)
                answer_text, audio_seconds = await asyncio.to_thread(self.stt.transcribe, samples)
            if not answer_text:
                raise ValueError("Không nghe thấy câu trả lời, bạn nói lại được không?")

            turn = session.turns.get(i) or Turn(i, session.questions[i])
            turn.answer = answer_text
            turn.confirmed = confirm
            turn.answered_at = time.time()
            session.turns[i] = turn
            if confirm and session.next_index == i:
                session.next_index = i + 1
            session.touch()

            result = {"sessionid": session.id, "index": i, "answerText": answer_text,
                      "confirmed": confirm,
                      "durationSec": duration_sec if duration_sec is not None
                      else (round(audio_seconds) if audio_seconds else None)}
            if ask_next and confirm:
                result["next"] = await self._question(session, speak=speak_next)
            return result

    async def evaluate(self, session_id: str) -> dict:
        """Rubric 5 chiều cho FE relay sang POST /{id}/evaluation của BE. Không chấm ngoại hình hay giọng vùng miền."""
        session = self.store.get(session_id)
        async with session.lock:
            scored = self.generator.evaluate(session.job_title, session.jd_text,
                                             session.history())
            session.touch()
            return {"sessionid": session.id, **scored,
                    "rubricVersion": self.settings.rubric_version,
                    "turns": len(session.turns)}
