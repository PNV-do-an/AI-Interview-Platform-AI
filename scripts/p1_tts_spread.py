"""Đo ngân sách trễ phần nghe của FE: sau khi gửi câu hỏi, bao lâu avatar cất tiếng và nói hết bao lâu.

FE không được chờ API: `/human` của LiveTalking là fire-and-forget nên `/speak` và
`GET /question` trả về ngay, còn âm thanh xuất hiện muộn hơn nhiều. Script này gửi 10 câu
dài ngắn khác nhau qua `/speak` rồi poll `/speaking` để lấy phân phối thật, từ đó chọn
timeout mở micro và timeout báo "avatar im lặng".

    .venv/Scripts/python.exe scripts/p1_tts_spread.py
"""
from __future__ import annotations

import statistics
import sys
import time

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")

from scripts.p1_ai_service_e2e import AI, fail, open_avatar_session  # noqa: E402

# Dài dần: câu ngắn để đo nền, câu dài để xem trễ có tỷ lệ với số chữ không.
TEXTS = [
    "Bạn giới thiệu về mình nhé.",
    "Bạn làm Backend được mấy năm?",
    "Bạn đã dùng Docker trong dự án nào cụ thể?",
    "Kể một quyết định kỹ thuật bạn thấy sai và vì sao.",
    "Giải thích cách bạn thiết kế cache cho bảng giá, gồm cả lý do chọn Redis.",
    "Nếu dịch vụ giảm từ 300 mili giây xuống 40 mili giây nhờ cache, bạn chứng minh điều đó "
    "thế nào với team, và bạn theo dõi những chỉ số nào sau khi lên production?",
    "Bạn sẽ làm gì khi một cuộc gọi tới PostgreSQL chậm dần mỗi tuần, không có lỗi nào được "
    "ghi lại, cảnh báo chưa được cấu hình, và product manager muốn xử lý trong một sprint tới? "
    "Hãy trình bày theo thứ tự bạn sẽ làm, từ lúc nhận tin tới lúc đóng vấn đề.",
]

POLL = 0.2
ONSET_CAP = 40.0
SPEECH_CAP = 90.0


def poll_until(sid: str, want: bool, cap: float) -> float | None:
    """Trả về số giây cần để /speaking chuyển sang `want`, hoặc None nếu vượt `cap`."""
    t0 = time.time()
    while time.time() - t0 < cap:
        if requests.get(AI + f"/api/v1/ai/session/{sid}/speaking", timeout=10).json().get("speaking") == want:
            return time.time() - t0
        time.sleep(POLL)
    return None


def main() -> None:
    avatar_sid, close_avatar = open_avatar_session()
    sess = requests.post(AI + "/api/v1/ai/session", timeout=10, json={
        "jobTitle": "Backend Java",
        "jdText": "Chúng tôi cần Backend Java: Spring Boot, PostgreSQL, Docker, Redis.",
        "avatarSessionId": avatar_sid,
    }).json()
    sid = sess["sessionid"]

    rows = []
    for text in TEXTS:
        words = len(text.split())
        t0 = time.time()
        r = requests.post(AI + f"/api/v1/ai/session/{sid}/speak", timeout=30, json={"text": text})
        http_dt = time.time() - t0
        if r.status_code != 200:
            fail(f"/speak -> {r.status_code} {r.text[:200]}")

        onset = poll_until(sid, True, ONSET_CAP)
        spoken = poll_until(sid, False, SPEECH_CAP) if onset is not None else None
        if onset is None:
            print(f"{words:4d} chữ  /speak {http_dt:5.2f}s  AVATAR IM LẶNG quá {ONSET_CAP:.0f}s")
            rows.append((words, http_dt, None, None))
            continue
        print(f"{words:4d} chữ  /speak {http_dt:5.2f}s  cất tiếng sau {onset:6.2f}s  "
              f"nói hết {('%.2f' % spoken) if spoken is not None else 'chưa dừng'}s")
        rows.append((words, http_dt, onset, spoken))
        time.sleep(0.6)

    ok = [row[2] for row in rows if row[2] is not None]
    silent = sum(1 for row in rows if row[2] is None)
    if not ok:
        fail("không lần nào avatar nói — không có số để báo")
    ok.sort()
    print("\n=== ngân sách trễ cho FE ===")
    print(f"mẫu: {len(rows)} câu, {silent} câu avatar im lặng")
    print(f"cất tiếng: nhanh nhất {ok[0]:.2f}s, trung vị {statistics.median(ok):.2f}s, "
          f"chậm nhất {ok[-1]:.2f}s")
    print(f"API /speak không chặn: chậm nhất {max(row[1] for row in rows):.2f}s")
    print("=> FE: hiện phụ đề ngay khi có questionText, poll /speaking tới "
          f"{ok[-1] + 5:.0f}s rồi bấm 'nghe lại' qua /speak nếu vẫn im lặng.")

    requests.delete(AI + f"/api/v1/ai/session/{sid}", timeout=10)
    close_avatar()
    # pc.close() chỉ giải phóng khi tiến trình còn sống đủ lâu để gửi lời từ biệt. Đo 26/10:
    # thoát ngay sau close thì phiên vẫn còn nguyên sau hơn một phút, và LiveTalking không có
    # route nào để đóng hộ — mỗi lần chạy lại script mà không chờ sẽ chiếm thêm một trong
    # max_session (5) chỗ.
    LT = "http://127.0.0.1:8010"
    time.sleep(3)
    left = requests.get(LT + "/api/admin/sessions", timeout=10).json()["data"]["sessions"]
    print("   phiên avatar còn lại sau khi đóng WebRTC:", len(left))


if __name__ == "__main__":
    main()
