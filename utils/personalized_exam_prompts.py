"""个性化出卷提示词。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from utils.exam_prompts import (
    _build_writing_prompt,
    _build_banked_cloze_prompt,
    _build_long_reading_prompt,
    _build_close_reading_prompt,
    _build_translation_prompt,
)

EXAM_SPECS = {
    "CET4": {
        "paper_name": "大学英语四级（CET-4）模拟试卷",
        "writing_format": "For this part, you are allowed 30 minutes to write an essay on the topic: [题目]. You should write at least 120 words but no more than 180 words.",
        "writing_type": "议论文或书信",
        "writing_topics": "校园生活、社会现象、教育话题",
        "banked_cloze_length": "200-250词",
        "banked_cloze_topics": "科普、社会、文化类",
        "long_reading_length": "约1000词",
        "long_reading_topics": "社会现象、科技发展、文化比较",
        "close_reading_length": "300-350词",
        "close_reading_topics": "第一篇为科技类，第二篇为人文类",
        "translation_length": "140-160字",
        "translation_topics": "中国文化、历史、社会发展",
        "close_reading_focus": "包含主旨题和细节题，尽量保持四级真题风格。",
        "translation_label": "汉译英",
    },
    "CET6": {
        "paper_name": "大学英语六级（CET-6）模拟试卷",
        "writing_format": "For this part, you are allowed 30 minutes to write an essay on the topic: [题目]. You should write at least 150 words but no more than 200 words.",
        "writing_type": "议论文或图表分析",
        "writing_topics": "社会热点、科技伦理、文化现象",
        "banked_cloze_length": "250-300词",
        "banked_cloze_topics": "学术、经济、心理类（词汇难度高于四级）",
        "long_reading_length": "约1200词",
        "long_reading_topics": "学术研究、社会评论、国际视野",
        "close_reading_length": "400-450词",
        "close_reading_topics": "第一篇为科技/经济类，第二篇为人文/哲学类",
        "translation_length": "180-200字",
        "translation_topics": "中国文化经典、历史事件、哲学思想",
        "close_reading_focus": "包含推理题、态度题、主旨题，难度略高于四级。",
        "translation_label": "汉译英",
    },
}


def _normalize_exam_level(level: str) -> str:
    value = str(level or "CET4").strip().upper()
    if value in {"4", "CET-4", "CET4"}:
        return "CET4"
    if value in {"6", "CET-6", "CET6"}:
        return "CET6"
    return "CET4"


def _get_exam_spec(level: str) -> dict:
    return EXAM_SPECS[_normalize_exam_level(level)]


def _format_word_sample(words) -> str:
    lines = []
    for index, item in enumerate(words, start=1):
        if not isinstance(item, dict):
            continue
        word = item.get("word", "")
        meaning = item.get("meaning") or item.get("cnMean") or item.get("translation") or item.get("explanation") or ""
        lines.append(f"{index}. {word} - {meaning}" if meaning else f"{index}. {word}")
    return "\n".join(lines)


# 注意：_build_*_prompt 函数是从 utils.exam_prompts 导入的，包含难度控制逻辑


def _format_word_list(words: Iterable[Dict[str, Any]], limit: int = 20) -> str:
    items: List[str] = []
    for index, item in enumerate(words or [], start=1):
        if index > limit:
            break
        if not isinstance(item, dict):
            continue
        word = item.get("word") or item.get("headWord") or ""
        meaning = item.get("meaning") or item.get("cnMean") or item.get("translation") or item.get("explanation") or ""
        if word:
            items.append(f"{index}. {word} - {meaning}" if meaning else f"{index}. {word}")
    return "\n".join(items) if items else "暂无"


def _format_recent_scores(recent_scores: Iterable[Dict[str, Any]]) -> str:
    items: List[str] = []
    for index, score in enumerate(recent_scores or [], start=1):
        total_score = float(score.get("total_score", 0) or 0)
        total_possible = float(score.get("total_possible", 0) or 0)
        accuracy = (total_score / total_possible * 100) if total_possible else 0
        items.append(f"{index}. {int(total_score)}/{int(total_possible)} = {accuracy:.1f}%")
    return "\n".join(items) if items else "暂无"


def _build_personalization_note(
    *,
    level: str,
    recent_scores: Iterable[Dict[str, Any]],
    wrong_words: Iterable[Dict[str, Any]],
    recommended_difficulty: int,
    recent_n: int,
) -> str:
    wrong_word_text = _format_word_list(wrong_words, limit=20)
    recent_score_text = _format_recent_scores(recent_scores)
    return f"""
【个性化出题要求】
- 当前级别：{level}
- 推荐难度：{recommended_difficulty}
- 根据近{recent_n}次成绩平均正确率调整题目整体难度，优先贴合当前薄弱点。
- 试题内容要尽量结合错词库中的高频错词，重点覆盖常错词、易混词和近义词。
- 不要直接把错词列表原样塞进题面，应该自然融入文章、题干或选项语境中。
- 生成风格仍需保持四级/六级真题感。

近{recent_n}次成绩概览：
{recent_score_text}

错词参考：
{wrong_word_text}
""".strip()


def build_personalized_writing_prompt(level: str, words, recent_scores, wrong_words, recommended_difficulty: int, recent_n: int) -> str:
    return _build_writing_prompt(level, words) + "\n\n" + _build_personalization_note(
        level=level,
        recent_scores=recent_scores,
        wrong_words=wrong_words,
        recommended_difficulty=recommended_difficulty,
        recent_n=recent_n,
    )


def build_personalized_banked_cloze_prompt(level: str, words, recent_scores, wrong_words, recommended_difficulty: int, recent_n: int) -> str:
    return _build_banked_cloze_prompt(level, recommended_difficulty, words) + "\n\n" + _build_personalization_note(
        level=level,
        recent_scores=recent_scores,
        wrong_words=wrong_words,
        recommended_difficulty=recommended_difficulty,
        recent_n=recent_n,
    )


def build_personalized_long_reading_prompt(level: str, words, recent_scores, wrong_words, recommended_difficulty: int, recent_n: int) -> str:
    return _build_long_reading_prompt(level, recommended_difficulty, words) + "\n\n" + _build_personalization_note(
        level=level,
        recent_scores=recent_scores,
        wrong_words=wrong_words,
        recommended_difficulty=recommended_difficulty,
        recent_n=recent_n,
    )


def build_personalized_close_reading_prompt(level: str, article_no: int, words, recent_scores, wrong_words, recommended_difficulty: int, recent_n: int) -> str:
    return _build_close_reading_prompt(level, article_no, recommended_difficulty, words) + "\n\n" + _build_personalization_note(
        level=level,
        recent_scores=recent_scores,
        wrong_words=wrong_words,
        recommended_difficulty=recommended_difficulty,
        recent_n=recent_n,
    )


def build_personalized_translation_prompt(level: str, words, recent_scores, wrong_words, recommended_difficulty: int, recent_n: int) -> str:
    return _build_translation_prompt(level, words) + "\n\n" + _build_personalization_note(
        level=level,
        recent_scores=recent_scores,
        wrong_words=wrong_words,
        recommended_difficulty=recommended_difficulty,
        recent_n=recent_n,
    )