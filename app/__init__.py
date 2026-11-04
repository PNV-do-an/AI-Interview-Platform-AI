"""AI service cho luồng phỏng vấn có avatar.

Biên của nó: FE (trình duyệt) ↔ service này (hỏi đáp + tiếng nói + avatar) ↔ LiveTalking.
Dữ liệu phỏng vấn không nằm ở đây — BE (spec 012) mới là nơi lưu, service chỉ giữ hội thoại
đang mở trong RAM để biết câu hỏi tiếp theo là gì.
"""
