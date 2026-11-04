"""Client LiveTalking — đường duy nhất service này nói chuyện với tiến trình avatar.

Hợp đồng đã đọc trực tiếp trong vendored/LiveTalking (app.py:180, server/rtc_manager.py:79,
server/routes.py):
  POST /offer          {sdp,type,avatar?} -> {sdp,type,sessionid}; lỗi = HTTP 200 + {code:-1,msg}
  POST /human          {sessionid,type:"echo",text} -> avatar nói bằng TTS của chính nó
  POST /is_speaking    {sessionid} -> {code,msg,data:bool}
  POST /interrupt_talk {sessionid} -> {code,msg}
Giọng đọc là EdgeTTS đã bật sẵn trong tiến trình avatar (config/livetalking.yaml:
tts=edgetts, REF_FILE=vi-VN-HoaiMyNeural) — đo P0 ngày 26/10 chạy qua đường này nên khẩu hình
đã được kiểm chứng; service này không tổng hợp âm thanh lại lần hai.
Vì /offer trả body trần khi thành công nhưng có `code` khi thất bại, mọi phản hồi đều phải soi `code`
trước khi tin — không có bước đó thì hết chỗ session bị từ chối sẽ lộ ra thành KeyError.
"""
from __future__ import annotations

from typing import Any, Optional

import aiohttp


class AvatarError(RuntimeError):
    """LiveTalking từ chối hoặc không phản hồi — nguyên văn msg của nó, dịch khi hết chỗ."""


class AvatarClient:
    def __init__(self, base_url: str, avatar_id: str, timeout_sec: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.avatar_id = avatar_id
        self.timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _client(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            async with (await self._client()).post(self.base_url + path, json=payload) as resp:
                if resp.status != 200:
                    raise AvatarError(f"Avatar trả HTTP {resp.status} cho {path}")
                return await resp.json(content_type=None)
        except aiohttp.ClientError as e:
            raise AvatarError(f"Không gọi được avatar ở {self.base_url}: {e}") from e

    @staticmethod
    def _check(body: dict, path: str) -> dict:
        if int(body.get("code", 0)) != 0:
            raise AvatarError(f"{path}: {body.get('msg', 'lỗi không rõ')}")
        return body

    async def offer(self, sdp: str, sdp_type: str = "offer") -> dict:
        """Ký gửi SDP của trình duyệt, nhận SDP trả lời + sessionid của LiveTalking.

        Tiến trình avatar nhận tối đa max_session phiên cùng lúc (5 theo config hiện tại); hết chỗ
        thì /offer trả "Maximum session limit reached" — phải báo về FE chứ không được để treo.
        """
        body = self._check(await self._post("/offer",
                                            {"sdp": sdp, "type": sdp_type, "avatar": self.avatar_id}),
                           "/offer")
        if "sdp" not in body or "sessionid" not in body:
            raise AvatarError("/offer không trả về sdp/sessionid")
        return {"answerSdp": body["sdp"], "answerType": body.get("type", "answer"),
                "avatarSessionId": body["sessionid"]}

    async def speak_text(self, session_id: str, text: str) -> None:
        """Đẩy chữ cho TTS của LiveTalking: nó tự tổng hợp, tự máy miệng, tự stream qua WebRTC."""
        self._check(await self._post("/human", {"sessionid": str(session_id),
                                                 "type": "echo", "text": text}), "/human")

    async def speaking(self, session_id: str) -> bool:
        body = self._check(await self._post("/is_speaking", {"sessionid": str(session_id)}),
                           "/is_speaking")
        return bool(body.get("data"))

    async def interrupt(self, session_id: str) -> None:
        self._check(await self._post("/interrupt_talk", {"sessionid": str(session_id)}),
                    "/interrupt_talk")

    async def active_sessions(self) -> list[dict]:
        try:
            async with (await self._client()).get(self.base_url + "/api/admin/sessions") as resp:
                body = await resp.json(content_type=None)
        except (aiohttp.ClientError, ValueError) as e:
            raise AvatarError(f"Không đọc được danh sách phiên avatar: {e}") from e
        return list(self._check(body, "/api/admin/sessions").get("data", {}).get("sessions", []))
