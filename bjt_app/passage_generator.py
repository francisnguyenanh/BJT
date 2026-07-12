# -*- coding: utf-8 -*-
"""Generate a BJT-style (読解) reading comprehension passage via AI,
built around that day's rotating focus vocab/grammar/phrases.

BJT's real 読解 section mixes short internal notices, medium-length
emails/reports, and long reports/contracts/regulations — LENGTH_PRESETS
mirrors those three document shapes.
"""

import json
import random
import re

from bjt_app import ai_provider, storage

CONFIG_PATH_DEFAULT = ai_provider.CONFIG_PATH_DEFAULT

# Topic pools, one per exam level, following the mapping:
#   N2  -> Con người & đời sống xã hội (dễ hiểu, dễ đồng cảm)
#   N1  -> Tư duy & triết lý (trừu tượng, cần tư duy logic cao)
#   BJT -> Tiền bạc, công việc & quy trình (thực tế, cần chính xác tuyệt đối)
TOPIC_POOLS = {
    "N2": [
        {
            "name": "Tâm lý học & Kỹ năng sống (Giao tiếp)",
            "hint": "Cách con người tương tác, nghệ thuật lắng nghe, quản lý cảm xúc, tại sao giới trẻ ngày nay ngại giao tiếp trực tiếp.",
        },
        {
            "name": "Văn hóa & Đời sống Nhật Bản",
            "hint": "Ý nghĩa của các phong tục truyền thống, sự thay đổi trong lối sống của người Nhật (ăn uống, nhà ở), góc nhìn của người nước ngoài về Nhật Bản.",
        },
        {
            "name": "Môi trường & Động thực vật",
            "hint": "Biến đổi khí hậu, các phát minh xanh, tập tính của một loài động vật cụ thể (ví dụ: cách loài kiến giao tiếp, sự thông minh của loài quạ).",
        },
        {
            "name": "Giáo dục & Nuôi dạy con cái",
            "hint": "Phương pháp giáo dục ở trường học, tầm quan trọng của việc để trẻ em tự lập, ảnh hưởng của công nghệ đến học đường.",
        },
        {
            "name": "Thông báo & Tìm kiếm thông tin",
            "hint": "Nội quy thư viện, hướng dẫn sử dụng thẻ bưu điện, lịch trình tour du lịch, điều kiện nhận học bổng.",
        },
    ],
    "N1": [
        {
            "name": "Triết học, Nhân sinh quan & Bản chất con người",
            "hint": "Định nghĩa về hạnh phúc, ý nghĩa của thời gian, mối quan hệ giữa \"cái tôi\" và \"xã hội\", sự cô độc trong thế giới hiện đại.",
        },
        {
            "name": "Khoa học & Công nghệ (Góc nhìn vĩ mô)",
            "hint": "Trí tuệ nhân tạo (AI) và đạo đức con người, tác động của công nghệ sinh học, mối quan hệ giữa khoa học và nghệ thuật.",
        },
        {
            "name": "Ngôn ngữ học & Văn học",
            "hint": "Bản chất của việc dịch thuật, sự tiến hóa của ngôn ngữ, tại sao con người cần đọc sách, phân tích cấu trúc của các tác phẩm văn học.",
        },
        {
            "name": "Xã hội học & Kinh tế vĩ mô",
            "hint": "Già hóa dân số, toàn cầu hóa và sự phai nhạt bản sắc văn hóa, cấu trúc kinh tế thay đổi ảnh hưởng thế nào đến tâm lý con người.",
        },
        {
            "name": "Nghệ thuật & Thẩm mỹ",
            "hint": "Cách cảm thụ cái đẹp (như trà đạo, gốm sứ, tranh ảnh), sự khác biệt giữa nghệ thuật truyền thống và hiện đại.",
        },
    ],
    "BJT": [
        {
            "name": "Giao dịch & Quan hệ khách hàng",
            "hint": "Báo giá, thương lượng giá cả, xác nhận lịch trình ký kết hợp đồng, giải quyết khiếu nại (claim) từ khách hàng, thư cảm ơn sau hội chợ.",
        },
        {
            "name": "Vận hành nội bộ công ty",
            "hint": "Thông báo thay đổi nhân sự (bổ nhiệm giám đốc mới), quy định về trang phục mùa hè (Cool Biz), hướng dẫn sử dụng hệ thống IT mới, thông báo họp khẩn.",
        },
        {
            "name": "Báo cáo & Phân tích thị trường",
            "hint": "Báo cáo doanh thu quý, phân tích xu hướng tiêu dùng của giới trẻ, đề xuất dự án phát triển sản phẩm mới (Planning).",
        },
        {
            "name": "Quản trị & Đào tạo nhân sự",
            "hint": "Tài liệu hướng dẫn kỹ năng tiếp khách, quy trình xử lý khi xảy ra sự cố rò rỉ thông tin, cẩm nang văn hóa ứng xử trong công sở (Business Manners).",
        },
        {
            "name": "Kinh tế & Số liệu",
            "hint": "Đọc hiểu các bảng biểu về thị phần, biểu đồ cột về tình hình xuất nhập khẩu, biểu đồ đường thể hiện biến động giá nguyên vật liệu.",
        },
    ],
}

LENGTH_PRESETS = {
    "short": {
        "label": "Ngắn",
        "word_range": "380-420",
        "question_count": 3,
        "batch_sizes": {"vocab": 8, "grammar": 1, "phrase": 1},
    },
    "medium": {
        "label": "Trung bình",
        "word_range": "750-850",
        "question_count": 5,
        "batch_sizes": {"vocab": 14, "grammar": 2, "phrase": 2},
    },
    "long": {
        "label": "Dài",
        "word_range": "1150-1250",
        "question_count": 7,
        "batch_sizes": {"vocab": 20, "grammar": 3, "phrase": 3},
    },
}
DEFAULT_LENGTH = "medium"

# Reading level is independent of length: any length can be paired with any
# level (or "random"). LEVEL_ORDER lists the concrete levels; "random" is
# resolved to one of them at generation time.
LEVEL_ORDER = ["N2", "N1", "BJT"]
LEVEL_LABELS = {"N2": "N2", "N1": "N1", "BJT": "BJT", "random": "🎲 Random"}
DEFAULT_LEVEL_BY_LENGTH = {"short": "N2", "medium": "N1", "long": "BJT"}

LEVEL_META = {
    "N2": {
        "exam_label": "JLPT N2",
        "doc_type": (
            "một bài viết kiểu tạp chí/blog hoặc bài đọc thông tin thực tế "
            "(エッセイ、コラム、お知らせ、案内文) xoay quanh đời sống xã hội, gần gũi, dễ đồng cảm"
        ),
        "level_note": (
            "Đây là bài đọc tương đương JLPT N2: nội dung gần gũi đời sống, dễ đồng cảm, "
            "nhưng phải dùng từ vựng/ngữ pháp N2 tự nhiên, không quá đơn giản."
        ),
    },
    "N1": {
        "exam_label": "JLPT N1",
        "doc_type": (
            "một bài luận/bài phê bình mang tính tư duy trừu tượng, lập luận chặt chẽ "
            "(評論文、論説文) với câu văn phức tạp, nhiều liên từ và cấu trúc logic"
        ),
        "level_note": (
            "Đây là bài đọc tương đương JLPT N1: nội dung trừu tượng, mang tính triết lý/tư duy "
            "logic cao, câu văn phức tạp, đòi hỏi suy luận sâu, dùng nhiều mẫu ngữ pháp N1."
        ),
    },
    "BJT": {
        "exam_label": "BJT 700 điểm",
        "doc_type": (
            "một báo cáo/quy định/hợp đồng/email nội bộ dài, nhiều đoạn, có thể có mục đánh số "
            "hoặc số liệu cụ thể (report/規定/契約書/ビジネスメール)"
        ),
        "level_note": (
            "Đây là bài đọc thuộc phần 読解 của kỳ thi BJT (Business Japanese Proficiency Test) "
            "hạng khoảng 700 điểm: văn phong business chuẩn mực, chính xác tuyệt đối về số liệu/"
            "quy trình/thời hạn, dùng kính ngữ phù hợp với ngữ cảnh công việc thực tế."
        ),
    },
}


def resolve_level(level: str, length: str) -> str:
    """Turn a requested level ("N2"/"N1"/"BJT"/"random"/None) into a
    concrete level, picking randomly when the user asked for random."""
    if level == "random":
        return random.choice(LEVEL_ORDER)
    if level in LEVEL_ORDER:
        return level
    return DEFAULT_LEVEL_BY_LENGTH.get(length, "N2")


def pick_topic(exam_level: str) -> dict:
    pool = TOPIC_POOLS.get(exam_level) or TOPIC_POOLS["N2"]
    return random.choice(pool)


def _build_prompt(focus: dict, length_preset: dict, level_meta: dict, topic: dict) -> str:
    def fmt(items, with_reading=True):
        lines = []
        for it in items:
            if with_reading and it.get("reading"):
                lines.append(f"- {it['term']} ({it['reading']}): {it['meaning']}")
            else:
                lines.append(f"- {it['term']}: {it['meaning']}")
        return "\n".join(lines) if lines else "(không có)"

    vocab_block = fmt(focus.get("vocab", []))
    grammar_block = fmt(focus.get("grammar", []), with_reading=False)
    phrase_block = fmt(focus.get("phrase", []), with_reading=False)

    return f"""Bạn là người soạn đề thi đọc hiểu tiếng Nhật cấp độ {level_meta['exam_label']}.

{level_meta['level_note']}

CHỦ ĐỀ bắt buộc của bài đọc: "{topic['name']}" — {topic['hint']}
Hãy tự chọn một khía cạnh/tình huống cụ thể trong chủ đề này, KHÔNG viết chung chung, hời hợt.

Hãy viết {level_meta['doc_type']}, bằng tiếng Nhật tự nhiên đúng văn phong của thể loại trên,
dài khoảng {length_preset['word_range']} chữ Nhật (đếm cả kanji/kana, không tính dấu câu), LỒNG GHÉP
một cách tự nhiên các từ vựng và mẫu ngữ pháp sau (không cần dùng hết 100%, nhưng ưu tiên dùng
nhiều nhất có thể một cách tự nhiên, không gượng ép, không liệt kê máy móc):

TỪ VỰNG CẦN DÙNG:
{vocab_block}

NGỮ PHÁP / QUY TẮC KÍNH NGỮ CẦN DÙNG:
{grammar_block}

MẪU CÂU BUSINESS CẦN DÙNG:
{phrase_block}

Sau đoạn văn, viết ĐÚNG {length_preset['question_count']} câu hỏi trắc nghiệm đọc hiểu
(hỏi về nội dung, ý định người viết, cách phản hồi phù hợp, hoặc suy luận), mỗi câu 4 lựa
chọn A-D, chỉ đúng 1 đáp án. Độ khó câu hỏi phải tương xứng với {level_meta['exam_label']}.

Cuối cùng, hãy TỰ RÀ SOÁT LẠI chính đoạn văn passage_jp bạn vừa viết (không phải danh sách từ
vựng/ngữ pháp bắt buộc ở trên) và trích xuất:

- "vocab_glossary": TẤT CẢ từ vựng (danh từ, động từ, tính từ, phó từ, thành ngữ...) THỰC SỰ
  xuất hiện trong passage_jp có cấp độ N3 hoặc cao hơn (N3/N2/N1), kèm cách đọc hiragana và
  nghĩa tiếng Việt ngắn gọn. Bỏ qua trợ từ và từ vựng N5/N4 quá cơ bản (これ、あります、する...).
  Không bỏ sót từ nào ở mức N3+ thực sự có trong bài.
- "grammar_glossary": TẤT CẢ mẫu ngữ pháp N2, N1, hoặc mẫu ngữ pháp/kính ngữ đặc trưng văn phong
  business (BJT) THỰC SỰ xuất hiện trong passage_jp (bỏ qua ngữ pháp N5/N4 cơ bản), kèm cấu trúc
  ngắn gọn, nghĩa tiếng Việt, và câu ví dụ phải là CÂU TRÍCH NGUYÊN VĂN từ chính passage_jp có
  chứa mẫu ngữ pháp đó (không tự đặt câu mới).

TRẢ VỀ DUY NHẤT một JSON hợp lệ (không markdown, không giải thích thêm) theo đúng schema:
{{
  "title": "tên ngắn cho bài đọc (tiếng Việt)",
  "scenario": "mô tả ngắn bối cảnh bằng tiếng Việt (1 câu)",
  "passage_jp": "toàn bộ đoạn văn tiếng Nhật",
  "questions": [
    {{
      "question": "câu hỏi bằng tiếng Nhật",
      "options": ["lựa chọn A", "lựa chọn B", "lựa chọn C", "lựa chọn D"],
      "answer_index": 0,
      "explanation": "giải thích ngắn bằng tiếng Việt vì sao đáp án đó đúng"
    }}
  ],
  "vocab_glossary": [
    {{"term": "từ tiếng Nhật", "reading": "cách đọc hiragana", "meaning": "nghĩa tiếng Việt", "level": "N3|N2|N1"}}
  ],
  "grammar_glossary": [
    {{"pattern": "mẫu ngữ pháp", "structure": "cấu trúc ngắn gọn", "meaning": "nghĩa tiếng Việt", "example": "câu trích nguyên văn từ passage_jp", "level": "N2|N1|BJT"}}
  ]
}}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output: {text[:300]}")
    return json.loads(text[start : end + 1])


def _dedupe_by_term(glossary: list, existing_terms: set, term_field="term") -> list:
    seen = set(existing_terms)
    out = []
    for it in glossary or []:
        term = str(it.get(term_field) or it.get("term") or it.get("pattern") or "").strip()
        if not term or term in seen:
            continue
        seen.add(term)
        out.append(it)
    return out


def generate_passage(
    passage_id: str,
    focus: dict,
    calendar_date: str,
    length: str = DEFAULT_LENGTH,
    level: str = None,
    config_path: str = CONFIG_PATH_DEFAULT,
) -> dict:
    length_preset = LENGTH_PRESETS.get(length, LENGTH_PRESETS[DEFAULT_LENGTH])
    requested_level = level or DEFAULT_LEVEL_BY_LENGTH.get(length, "N2")
    exam_level = resolve_level(requested_level, length)
    level_meta = LEVEL_META.get(exam_level, LEVEL_META["N2"])
    topic = pick_topic(exam_level)
    prompt = _build_prompt(focus, length_preset, level_meta, topic)
    raw, provider_used = ai_provider.ask(prompt, config_path=config_path)
    parsed = _extract_json(raw)

    focus_vocab_terms = {v["term"] for v in focus.get("vocab", [])}
    focus_grammar_terms = {g["term"] for g in focus.get("grammar", [])}

    result = {
        "id": passage_id,
        "date": calendar_date,
        "length": length,
        "length_label": length_preset["label"],
        "level": requested_level,
        "exam_level": exam_level,
        "difficulty": level_meta["exam_label"],
        "topic": topic["name"],
        "provider": provider_used,
        "title": parsed.get("title", ""),
        "scenario": parsed.get("scenario", ""),
        "passage_jp": parsed.get("passage_jp", ""),
        "questions": parsed.get("questions", []),
        "focus_vocab": focus.get("vocab", []),
        "focus_grammar": focus.get("grammar", []),
        "focus_phrase": focus.get("phrase", []),
        "extra_vocab": _dedupe_by_term(parsed.get("vocab_glossary", []), focus_vocab_terms, "term"),
        "extra_grammar": _dedupe_by_term(parsed.get("grammar_glossary", []), focus_grammar_terms, "pattern"),
    }
    return result


def save_passage(result: dict) -> str:
    return storage.save_passage(result)


def load_passage(passage_id: str):
    return storage.load_passage(passage_id)


def delete_passage(passage_id: str) -> bool:
    return storage.delete_passage(passage_id)


def delete_all_passages() -> int:
    return storage.delete_all_passages()


if __name__ == "__main__":
    import sys

    from bjt_app.progress import get_daily_focus

    calendar_date = sys.argv[1] if len(sys.argv) > 1 else "test-day"
    length = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_LENGTH
    passage_id = f"{calendar_date}__{length}"

    preset = LENGTH_PRESETS.get(length, LENGTH_PRESETS[DEFAULT_LENGTH])
    focus = get_daily_focus(passage_id, batch_sizes=preset["batch_sizes"])
    result = generate_passage(passage_id, focus, calendar_date, length=length)
    path = save_passage(result)
    print(f"Saved passage to {path}")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1000])
