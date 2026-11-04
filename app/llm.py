"""Sinh câu hỏi + chấm rubric.

Hai chế độ, chọn bằng biến môi trường, không có khóa nào trong mã nguồn:
  template  — mặc định, rule-based trên text JD, chạy offline được, đủ cho demo và CI.
  openai    — OpenAI-compatible (/chat/completions), dùng được Ollama/vLLM/Groq/OpenAI;
              cần AI_LLM_BASE_URL + AI_LLM_MODEL (+ AI_LLM_API_KEY nếu nhà cung cần khóa).
Rubric 5 chiều khớp hợp đồng BE spec 012: chuyenMon, duAn, tuDuy, truyenDat, mucKhop.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

RUBRIC_DIMENSIONS = ("chuyenMon", "duAn", "tuDuy", "truyenDat", "mucKhop")

# Kỹ thuật thường gặp trong JD lập trình — dùng để chọn câu hỏi theo đúng vị trí ứng tuyển.
SKILL_WORDS = [
    "java", "spring", "spring boot", "hibernate", "jpa", "quarkus", "nodejs", "node.js",
    "python", "django", "fastapi", "go", "golang", "c#", ".net", "php", "laravel", "ruby",
    "react", "reactjs", "vue", "angular", "nextjs", "typescript", "javascript",
    "mysql", "postgresql", "redis", "mongodb", "elasticsearch", "kafka", "rabbitmq", "graphql",
    "docker", "kubernetes", "terraform", "aws", "azure", "gcp", "ci/cd", "jenkins", "github actions",
    "rest", "api", "microservice", "websockets", "webrtc", "grpc", "oauth", "jwt",
    "unit test", "tdd", "git", "agile", "scrum", "machine learning", "llm",
]
NUMERIC_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(%|nhân|k\b|triệu|tỷ|ms|giây|phút|giờ|ngày|user|request|query|lượt|dòng|million|billion)",
    re.IGNORECASE)
FILLER_WORDS = ["thì", "là", "kiểu như", "cái đó", "nó nó", "giờ thì"]


def extract_skills(jd_text: str) -> list[str]:
    """Skill có trong JD, xếp theo thứ tự xuất hiện trong tin — kỹ thuật nêu trước đáng hỏi trước."""
    low = (jd_text or "").lower()
    hits = [(low.index(w), w) for w in SKILL_WORDS if w in low]
    found = [w for _, w in sorted(hits)]
    # "spring" nằm trong "spring boot": bỏ bản ngắn bị bản dài hơn che, giữ đúng một mục
    return [w for w in found if not any(w != o and w in o for o in found)]


def _title_of(role: str, jd_text: str) -> str:
    if role and role.strip():
        return role.strip()
    for line in (jd_text or "").splitlines():
        line = line.strip(" \t-•#:")
        if 3 < len(line) < 80 and line.lower() != line:  # dòng có hoa đầu thường là chức danh
            return line
    return "vị trí ứng tuyển"


class Turn:
    def __init__(self, index: int, question: str, answer: str | None = None) -> None:
        self.index = index
        self.question = question
        self.answer = answer
        self.confirmed = False
        self.answered_at: float | None = None

    def as_dict(self) -> dict:
        return {"index": self.index, "questionText": self.question, "answerText": self.answer,
                "confirmed": self.confirmed, "answeredAt": self.answered_at}


class TemplateGenerator:
    """Bộ sinh câu hỏi tất định, đọc JD. Không gọi mô hình nào cả nên không tốn tiền và không cần khóa."""

    def __init__(self, max_turns: int) -> None:
        self.max_turns = max_turns

    def next_question(self, role: str, jd_text: str, history: list[Turn], turn_index: int) -> str | None:
        skills = extract_skills(jd_text)
        primary = skills[0].title() if skills else _title_of(role, jd_text)
        last = history[-1] if history else None
        answered = [t for t in history if t.answer]

        def covered(skill: str) -> bool:
            return any(skill.lower() in (t.answer or "").lower() for t in answered)

        thin = [t for t in answered if len(t.answer or "") < 120]

        if turn_index == 0:
            return (f"Chào bạn, hôm nay mình phỏng vấn cho vị trí {_title_of(role, jd_text)}. "
                    f"Mở đầu, bạn giới thiệu gọn trong một phút: bạn làm gì, bao lâu, và điểm nào "
                    f"trong kinh nghiệm liên quan nhất tới {primary}?")

        # Hỏi dồn một lượt cho câu trả lời quá cộc — đây là chỗ phỏng vấn thật khác kịch bản cứng.
        if last and last.answer is not None and len(last.answer) < 60:
            return ("Mình thấy câu trả lời hơi ngắn. Bạn nói cụ thể hơn được không: bạn đã làm gì "
                    "trong đó, kết quả đo được là bao nhiêu?")

        asked_deep = sum(1 for t in answered if "thiết kế" in t.question or "gấp" in t.question)
        if asked_deep < 1 and turn_index >= 3 and skills:
            return (f"Giả sử hệ thống {skills[0].title()} của bạn phải chịu tải gấp 10 lần hiện tại. "
                    f"Bạn thiết kế lại thế nào, và đánh đổi gì về chi phí cũng như độ phức tạp?")

        if len(answered) >= 3 and any(t.answer and NUMERIC_RE.search(t.answer or "") is None
                                      and len(t.answer) >= 120 for t in answered[-3:]):
            if turn_index >= 4 and not any("con số" in t.question for t in history):
                return ("Những phần vừa rồi bạn kể khá chung. Cho mình một ví dụ có số: khối lượng dữ liệu, "
                        "số người dùng, thời gian cải thiện — con số nào cũng được.")

        uncovered = [s for s in skills if not covered(s)]
        if uncovered:
            skill = uncovered[0].title()
            return (f"Bạn đã dùng {skill} trong dự án nào cụ thể? Vai trò của bạn trong đó là gì, "
                    f"và nếu làm lại bạn đổi điều gì?")

        if not any("mâu thuẫn" in t.question for t in history):
            return ("Kể một lần bạn bất đồng kỹ thuật trong team. Bạn thuyết phục người kia thế nào, "
                    "và kết quả ra sao?")

        if not any("tại sao" in t.question or "động lực" in t.question for t in history):
            return (f"Tại sao bạn muốn làm vị trí {_title_of(role, jd_text)} ở công ty này, "
                    f"và bạn mong đợi học thêm điều gì trong một năm tới?")

        if not any("câu hỏi" in t.question for t in history) and turn_index >= 5:
            return "Phần mình hỏi hết. Bạn còn điều gì muốn bổ sung hoặc muốn hỏi lại ban tuyển dụng không?"

        if turn_index >= self.max_turns - 1:
            return None
        return (f"Quay lại {primary}: điều gì trong công việc hằng ngày của bạn ở mảng này "
                f"làm bạn mất thời gian nhất, và bạn đã xử lý ra sao?")

    def evaluate(self, role: str, jd_text: str, history: list[Turn]) -> dict:
        """Rubric tất định từ transcript. Rule-based, không AI — báo rõ với FE/BE là điểm loại tham khảo."""
        skills = extract_skills(jd_text)
        answered = [t for t in history if t.answer]
        text_all = " ".join((t.answer or "") for t in answered).lower()
        lengths = [len(t.answer or "") for t in answered]

        hit = [s for s in skills if s in text_all]
        coverage = len(hit) / len(skills) if skills else 0.0
        examples = sum(1 for t in answered if NUMERIC_RE.search(t.answer or ""))
        structured = sum(1 for t in answered
                         if re.search(r"\b(đầu tiên|sau đó|cuối cùng|vì vậy|kết quả)\b",
                                      (t.answer or "").lower()))
        fillers = sum(text_all.count(w) for w in FILLER_WORDS)
        answer_rate = len(answered) / max(1, len(history))

        def clamp(v: float) -> int:
            return int(max(0, min(100, round(v))))

        chuyen_mon = 40 + 60 * coverage
        du_an = 30 + 40 * min(1.0, examples / 2) + 30 * coverage
        tu_duy = 30 + 25 * min(1.0, structured / 3) + 25 * min(1.0, max(0, (sum(lengths) / max(1, len(lengths)) - 60) / 240)) + 20 * coverage
        truyen_dat = 85 - 5 * fillers + 15 * min(1.0, sum(lengths) / max(1, len(lengths)) / 400) - (10 if any(l < 40 for l in lengths) else 0)
        muc_khop = 25 + 75 * answer_rate

        dims = {
            "chuyenMon": clamp(chuyen_mon),
            "duAn": clamp(du_an),
            "tuDuy": clamp(tu_duy),
            "truyenDat": clamp(truyen_dat),
            "mucKhop": clamp(muc_khop),
        }
        strengths = []
        improvements = []
        if coverage >= 0.6:
            strengths.append("Bám đúng kỹ thuật tin tuyển dụng yêu cầu: " + ", ".join(hit[:5]))
        if examples >= 2:
            strengths.append("Có dẫn chứng định lượng, không kể chung chung")
        if structured >= 2:
            strengths.append("Trình bày có trình tự (bối cảnh -> hành động -> kết quả)")
        if coverage < 0.6:
            missing = [s for s in skills if s not in hit][:4]
            if missing:
                improvements.append("Chưa động tới các kỹ thuật JD yêu cầu: " + ", ".join(missing))
        if examples < 2:
            improvements.append("Thiếu con số cụ thể (kích thước dữ liệu, thời gian cải thiện, số người dùng)")
        if any(l < 120 for l in lengths):
            improvements.append("Vài câu trả lời quá ngắn, chưa đủ để người phỏng vấn đánh giá")
        if fillers >= 3:
            improvements.append("Còn nhiều từ đệm, nên nói thẳng vào ý chính")
        return {
            "rubric": dims,
            "strengths": ". ".join(strengths) or "Chưa đủ dữ liệu để ghi điểm mạnh.",
            "improvements": ". ".join(improvements) or "Chưa đủ dữ liệu để ghi điểm cần cải thiện.",
        }


class OpenAICompatibleGenerator:
    """Gọi /chat/completions: chạy với Ollama, vLLM, Groq, OpenAI... nhà nào cũng cùng kiểu gọi."""

    def __init__(self, base_url: str, api_key: str, model: str, max_turns: int, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_turns = max_turns
        self.timeout = timeout

    def _chat(self, system: str, user: str, expect_json: bool) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.7,
            "stream": False,
        }
        if expect_json:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(self.base_url + "/chat/completions",
                                    data=json.dumps(payload).encode("utf-8"),
                                    headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"LLM trả {e.code}: {e.read().decode(errors='ignore')[:200]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"Không gọi được LLM ở {self.base_url}: {e}") from e
        return body["choices"][0]["message"]["content"]

    def next_question(self, role: str, jd_text: str, history: list[Turn], turn_index: int) -> str | None:
        if turn_index >= self.max_turns:
            return None
        system = ("Bạn là người phỏng vấn kỹ thuật phần mềm bằng tiếng Việt. Hỏi một câu mỗi lần, "
                  "ngắn gọn tối đa 55 từ, bám tin tuyển dụng và câu trả lời trước của ứng viên. "
                  "Nếu ứng viên trả lời hời hợt thì đào sâu vào đúng chỗ đó, không hỏi lan man. "
                  'Trả về JSON: {"question": "..."} hoặc {"question": null} khi đã đủ.'
                  )
        convo = "\n".join(f"{t.index}. H: {t.question}\n   Đ: {t.answer or '(chưa trả lời)'}" for t in history[-8:])
        out = self._chat(system, f"Vị trí: {role}\nJD:\n{jd_text[:4000]}\n\nHội thoại tới giờ:\n{convo}")
        try:
            return json.loads(out)["question"]
        except (json.JSONDecodeError, KeyError):
            return out.strip()[:400]

    def evaluate(self, role: str, jd_text: str, history: list[Turn]) -> dict:
        system = ("Bạn chấm một buổi phỏng vấn kỹ thuật. Chỉ dựa trên năng lực công việc, không bình luận "
                  "về giới tính, ngoại hình hay giọng vùng miền. Trả về JSON đúng cấu trúc: "
                  '{"rubric":{"chuyenMon":int,"duAn":int,"tuDuy":int,"truyenDat":int,"mucKhop":int},'
                  '"strengths":"...","improvements":"..."} với mỗi điểm là số nguyên 0..100.')
        convo = "\n".join(f"{t.index}. H: {t.question}\n   Đ: {t.answer or ''}" for t in history)
        out = self._chat(system, f"Vị trí: {role}\nJD:\n{jd_text[:4000]}\n\nTranscript:\n{convo[:12000]}",
                         expect_json=True)
        data = json.loads(out)
        rubric = {k: int(max(0, min(100, round(float(data["rubric"][k]))))) for k in RUBRIC_DIMENSIONS}
        return {"rubric": rubric,
                "strengths": str(data.get("strengths", ""))[:4000],
                "improvements": str(data.get("improvements", ""))[:4000]}


def build_generator(settings) -> TemplateGenerator | OpenAICompatibleGenerator:
    if settings.llm_ready():
        return OpenAICompatibleGenerator(settings.llm_base_url, settings.llm_api_key,
                                         settings.llm_model, settings.max_turns)
    return TemplateGenerator(settings.max_turns)
