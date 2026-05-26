"""试卷批改工具（支持四六级写作、翻译自动评分 - 实际分数版）。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from utils.call_ai import call_ai_full, check_ai


def build_ai_feedback_payload(
    *,
    question_id: str,
    question_type: str,
    score_earned: float,
    score_possible: float,
    comment: str = "",
    strengths: Optional[List[str]] = None,
    issues: Optional[List[str]] = None,
    suggestions: Optional[List[str]] = None,
    reference_answer: str = "",
    rubric_points: Optional[List[str]] = None,
    raw_model_output: Optional[str] = None,
) -> Dict[str, Any]:
    """构造统一的 AI 反馈结构。"""
    return {
        "question_id": question_id,
        "question_type": question_type,
        "score_earned": score_earned,
        "score_possible": score_possible,
        "comment": comment,
        "strengths": strengths or [],
        "issues": issues or [],
        "suggestions": suggestions or [],
        "reference_answer": reference_answer,
        "rubric_points": rubric_points or [],
        "raw_model_output": raw_model_output,
    }


# ==============================================================================
# 写作评分（实际分数 0-15 分 + 报道分 0-106.5）
# ==============================================================================

def score_writing_cet46(
    user_answer: str,
    reference: str = "",
    word_min: int = 120,
    word_max: int = 180,
    is_cet6: bool = False
) -> Dict[str, Any]:
    """
    四六级写作评分（实际分数 0-15 分 + 报道分 0-106.5）
    根据内容、结构、语言、字数综合评分
    """
    # 空卷检测
    if not user_answer or user_answer.strip() == "":
        return {
            "score_earned": 0,
            "reported_score": 0,
            "score_possible": 15.0,
            "score_possible_reported": 106.5,
            "strengths": [],
            "issues": ["未作答"],
            "suggestions": ["请完成写作"],
            "comment": "未作答，0分"
        }
    
    words = len(user_answer.split())
    score = 8.0  # 基础分
    strengths = []
    issues = []
    suggestions = []

    # ========== 1. 字数评分（满分3分） ==========
    if words < word_min * 0.5:
        score = min(score, 2)
        issues.append(f"字数严重不足（{words}词），低于要求{word_min}词的50%")
        suggestions.append(f"写作需要达到{word_min}词以上")
    elif words < word_min:
        score -= 2
        issues.append(f"字数不足（{words}词），未达到{word_min}词要求")
        suggestions.append(f"建议扩充内容至{word_min}词以上")
    elif words > word_max * 1.2:
        score -= 1
        issues.append(f"字数略多（{words}词），建议精简至{word_max}词以内")
    elif word_min <= words <= word_max:
        score += 1
        strengths.append(f"字数符合要求（{words}词）")

    # ========== 2. 结构评分（满分3分） ==========
    structure_words = ['first', 'second', 'third', 'firstly', 'secondly', 'finally', 
                       'however', 'therefore', 'thus', 'conclusion', 'in summary', 
                       'on the one hand', 'on the other hand', 'moreover', 'furthermore']
    
    structure_count = sum(1 for w in structure_words if w in user_answer.lower())
    
    if structure_count >= 3:
        score += 2
        strengths.append("结构清晰，段落衔接自然")
    elif structure_count >= 1:
        score += 1
        strengths.append("基本结构完整")
    else:
        issues.append("缺少段落衔接词，结构不够清晰")
        suggestions.append("使用过渡词增强文章连贯性")

    # ========== 3. 内容质量评分（满分4分） ==========
    content_indicators = {
        'topic_relevant': ['important', 'essential', 'necessary', 'crucial', 'significant'],
        'reasoning': ['because', 'therefore', 'thus', 'lead to', 'result in', 'cause'],
        'examples': ['for example', 'for instance', 'such as', 'like'],
        'conclusion': ['conclusion', 'summary', 'finally', 'in conclusion', 'to sum up']
    }
    
    has_topic = any(w in user_answer.lower() for w in content_indicators['topic_relevant'])
    has_reasoning = any(w in user_answer.lower() for w in content_indicators['reasoning'])
    has_examples = any(w in user_answer.lower() for w in content_indicators['examples'])
    has_conclusion = any(w in user_answer.lower() for w in content_indicators['conclusion'])
    
    content_score = 0
    if has_topic:
        content_score += 1
        strengths.append("切题，观点明确")
    else:
        issues.append("未能紧扣主题")
    
    if has_reasoning:
        content_score += 1
        strengths.append("论证充分，逻辑清晰")
    else:
        issues.append("缺少充分论证")
    
    if has_examples:
        content_score += 1
        strengths.append("有具体例证支撑")
    
    if has_conclusion:
        content_score += 1
        strengths.append("结尾总结清晰")
    
    score += content_score

    # ========== 4. 语言质量评分（满分5分） ==========
    sentences = [s.strip() for s in user_answer.split('.') if len(s.strip()) > 5]
    sentence_count = len(sentences)
    
    proper_punctuation = sum(1 for s in sentences if s and s[0].isupper() and s[-1] in '.!?')
    punctuation_rate = proper_punctuation / max(sentence_count, 1)
    
    words_set = set(user_answer.lower().split())
    vocab_ratio = len(words_set) / max(words, 1)
    avg_sentence_length = words / max(sentence_count, 1)
    
    language_score = 0
    if punctuation_rate > 0.7:
        language_score += 1
        strengths.append("标点符号使用规范")
    else:
        issues.append("标点符号使用不规范")
    
    if vocab_ratio > 0.5:
        language_score += 1
        strengths.append("词汇丰富多样")
    else:
        issues.append("词汇重复较多")
    
    if 10 <= avg_sentence_length <= 25:
        language_score += 1
        strengths.append("句式长度适中")
    
    if punctuation_rate > 0.9 and vocab_ratio > 0.55:
        language_score += 2
        strengths.append("语言流畅，语法错误少")
    elif punctuation_rate > 0.7 and vocab_ratio > 0.45:
        language_score += 1
        strengths.append("语言基本通顺")
    else:
        issues.append("存在较多语法错误")
        suggestions.append("加强语法练习")
    
    score += language_score

    # ========== 5. 综合调整 ==========
    if is_cet6:
        score -= 1
    
    # 确保分数在 0-15 范围内
    score = max(0, min(15, round(score, 1)))
    
    # ========== 6. 换算报道分（0-106.5） ==========
    reported_score = int(round(score * 7.1))
    
    # 生成评语
    if score >= 13:
        comment = f"写作得分：{score}/15（报道分：{reported_score}/106.5）。优秀！语言流畅，结构清晰，观点明确。"
    elif score >= 10:
        comment = f"写作得分：{score}/15（报道分：{reported_score}/106.5）。良好！基本切题，语言通顺。"
    elif score >= 7:
        comment = f"写作得分：{score}/15（报道分：{reported_score}/106.5）。及格！存在一些错误，需要改进。"
    elif score >= 1:
        comment = f"写作得分：{score}/15（报道分：{reported_score}/106.5）。不及格，需要加强练习。"
    else:
        comment = "写作得分：0/15。未作答或严重偏离题目。"

    return {
        "score_earned": score,                    # 原始分 0-15
        "reported_score": reported_score,         # 报道分 0-106.5
        "score_possible": 15.0,
        "score_possible_reported": 106.5,
        "strengths": strengths[:5],
        "issues": issues[:5],
        "suggestions": suggestions[:3],
        "comment": comment,
        "word_count": words,
        "details": {
            "structure_score": structure_count,
            "content_score": content_score,
            "language_score": language_score
        }
    }


# ==============================================================================
# 翻译评分（实际分数 0-15 分 + 报道分 0-106.5）
# ==============================================================================

def score_translation_cet46(
    user_answer: str,
    reference_answer: str = "",
    is_cet6: bool = False
) -> Dict[str, Any]:
    """
    四六级翻译评分（实际分数 0-15 分 + 报道分 0-106.5）
    根据完整度、准确度、语言质量综合评分
    """
    # 空卷检测
    if not user_answer or user_answer.strip() == "":
        return {
            "score_earned": 0,
            "reported_score": 0,
            "score_possible": 15.0,
            "score_possible_reported": 106.5,
            "strengths": [],
            "issues": ["未作答"],
            "suggestions": ["请完成翻译"],
            "comment": "未作答，0分"
        }
    
    score = 8.0  # 基础分
    strengths = []
    issues = []
    suggestions = []
    
    user_len = len(user_answer)
    ref_len = max(len(reference_answer), 1)
    
    # ========== 1. 完整度评分（满分5分） ==========
    length_ratio = min(1.0, user_len / ref_len)
    
    if length_ratio >= 0.9:
        score += 2
        strengths.append("翻译完整，覆盖所有要点")
    elif length_ratio >= 0.7:
        score += 1
        strengths.append("基本完整，覆盖大部分要点")
    elif length_ratio >= 0.5:
        issues.append("翻译不完整，漏译部分内容")
        suggestions.append("确保翻译所有句子")
    else:
        score -= 2
        issues.append("翻译严重不完整，漏译大量内容")
        suggestions.append("需要完整翻译原文")
    
    # ========== 2. 准确度评分（满分5分） ==========
    user_words = set(user_answer.lower().split())
    ref_words = set(reference_answer.lower().split()) if reference_answer else set()
    
    if ref_words:
        word_match_ratio = len(user_words & ref_words) / len(ref_words)
    else:
        word_match_ratio = 0.5
    
    if word_match_ratio >= 0.8:
        score += 2
        strengths.append("用词准确，表达贴切")
    elif word_match_ratio >= 0.6:
        score += 1
        strengths.append("基本准确，核心词汇翻译正确")
    elif word_match_ratio >= 0.4:
        issues.append("部分翻译不准确")
        suggestions.append("注意词汇选择的准确性")
    else:
        score -= 2
        issues.append("翻译偏差较大，关键信息错误")
        suggestions.append("需要加强词汇积累")
    
    # ========== 3. 语言质量评分（满分5分） ==========
    sentences = [s.strip() for s in user_answer.split('.') if len(s.strip()) > 3]
    sentence_count = len(sentences)
    
    proper_start = sum(1 for s in sentences if s and s[0].isupper())
    proper_rate = proper_start / max(sentence_count, 1)
    
    proper_end = sum(1 for s in sentences if s and s[-1] in '.!?')
    end_rate = proper_end / max(sentence_count, 1)
    
    language_score = 0
    if proper_rate > 0.7:
        language_score += 1
        strengths.append("首字母大写规范")
    else:
        issues.append("首字母大写不规范")
    
    if end_rate > 0.7:
        language_score += 1
        strengths.append("标点符号使用正确")
    else:
        issues.append("句尾缺少标点符号")
    
    avg_len = len(user_answer) / max(sentence_count, 1)
    if 10 <= avg_len <= 40:
        language_score += 1
        strengths.append("句式结构合理")
    
    if language_score >= 3:
        language_score += 1
        strengths.append("语言流畅，语法错误少")
    
    score += language_score
    
    # ========== 4. 综合调整 ==========
    if is_cet6:
        score -= 1
    
    # 确保分数在 0-15 范围内
    score = max(0, min(15, round(score, 1)))
    
    # ========== 5. 换算报道分（0-106.5） ==========
    reported_score = int(round(score * 7.1))
    
    # 生成评语
    if score >= 13:
        comment = f"翻译得分：{score}/15（报道分：{reported_score}/106.5）。优秀！翻译准确流畅，用词贴切。"
    elif score >= 10:
        comment = f"翻译得分：{score}/15（报道分：{reported_score}/106.5）。良好！基本达意，语言通顺。"
    elif score >= 7:
        comment = f"翻译得分：{score}/15（报道分：{reported_score}/106.5）。及格！存在错误，需要改进。"
    elif score >= 1:
        comment = f"翻译得分：{score}/15（报道分：{reported_score}/106.5）。不及格，需要加强练习。"
    else:
        comment = "翻译得分：0/15。未作答。"

    return {
        "score_earned": score,                    # 原始分 0-15
        "reported_score": reported_score,         # 报道分 0-106.5
        "score_possible": 15.0,
        "score_possible_reported": 106.5,
        "strengths": strengths[:5],
        "issues": issues[:5],
        "suggestions": suggestions[:3],
        "comment": comment,
        "details": {
            "completeness": length_ratio,
            "accuracy": word_match_ratio if ref_words else 0.5,
            "language_score": language_score
        }
    }


_WRITING_BANDS = [
    (13.0, 15.0, "优秀！语言流畅，结构清晰，观点明确。"),
    (10.0, 12.0, "良好！基本切题，语言通顺。"),
    (7.0, 9.0, "及格！存在一些错误，需要改进。"),
    (1.0, 6.0, "不及格，需要加强练习。"),
    (0.0, 0.0, "未作答，0分。"),
]

_TRANSLATION_BANDS = [
    (13.0, 15.0, "优秀！翻译准确流畅，用词贴切。"),
    (10.0, 12.0, "良好！基本达意，语言通顺。"),
    (7.0, 9.0, "及格！存在错误，需要改进。"),
    (1.0, 6.0, "不及格，需要加强练习。"),
    (0.0, 0.0, "未作答，0分。"),
]


def _clamp_band_score(score: float, bands: List[tuple[float, float, str]]) -> float:
    for low, high, _ in bands:
        if low <= score <= high:
            return score
    if score <= 0:
        return 0.0
    if score >= 15:
        return 15.0
    for low, high, _ in bands:
        if score < low:
            return low
        if score > high:
            return high
    return score


def _band_comment(score: float, bands: List[tuple[float, float, str]]) -> str:
    for low, high, comment in bands:
        if low <= score <= high:
            return comment
    return ""


def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _build_writing_prompt(
    *,
    level: str,
    word_min: int,
    word_max: int,
    reference: str,
    user_answer: str,
) -> str:
    return (
        "你是CET写作阅卷老师。请按评分档位给出0-15原始分，并输出严格JSON。\n"
        f"【题型】writing\n【等级】{level}\n【字数要求】{word_min}-{word_max}\n"
        "【评分档位】\n"
        "- 13-15: 语言流畅、结构清晰、内容完整、观点明确\n"
        "- 10-12: 基本切题、语言通顺、结构基本清晰\n"
        "- 7-9: 及格水平，存在一些错误\n"
        "- 1-6: 不及格，错误较多\n"
        "- 0: 未作答或严重偏离题目\n"
        f"【参考答案】{reference}\n"
        f"【学生作答】{user_answer}\n"
        "【输出JSON字段】"
        "{\"score_earned\": 0-15, \"comment\": \"...\", \"strengths\": [], \"issues\": [], \"suggestions\": []}"
    )


def _build_translation_prompt(
    *,
    level: str,
    reference: str,
    user_answer: str,
) -> str:
    return (
        "你是CET翻译阅卷老师。请按评分档位给出0-15原始分，并输出严格JSON。\n"
        f"【题型】translation\n【等级】{level}\n"
        "【评分档位】\n"
        "- 13-15: 翻译准确流畅，用词贴切\n"
        "- 10-12: 基本达意，语言通顺\n"
        "- 7-9: 及格水平，存在一些错误\n"
        "- 1-6: 不及格，错误较多\n"
        "- 0: 未作答或严重偏离题目\n"
        f"【参考答案】{reference}\n"
        f"【学生作答】{user_answer}\n"
        "【输出JSON字段】"
        "{\"score_earned\": 0-15, \"comment\": \"...\", \"strengths\": [], \"issues\": [], \"suggestions\": []}"
    )


def _ai_score_writing(
    *,
    user_answer: str,
    reference: str,
    word_min: int,
    word_max: int,
    is_cet6: bool,
) -> Dict[str, Any]:
    if not user_answer or user_answer.strip() == "":
        return score_writing_cet46(
            user_answer=user_answer,
            reference=reference,
            word_min=word_min,
            word_max=word_max,
            is_cet6=is_cet6,
        )
    if not check_ai():
        return score_writing_cet46(
            user_answer=user_answer,
            reference=reference,
            word_min=word_min,
            word_max=word_max,
            is_cet6=is_cet6,
        )

    level = "CET6" if is_cet6 else "CET4"
    prompt = _build_writing_prompt(
        level=level,
        word_min=word_min,
        word_max=word_max,
        reference=reference,
        user_answer=user_answer,
    )
    result = call_ai_full(prompt, max_retries=2, max_tokens=600, timeout=120)
    payload = _extract_json_block(result.get("content", "") if result else "")
    if not payload:
        return score_writing_cet46(
            user_answer=user_answer,
            reference=reference,
            word_min=word_min,
            word_max=word_max,
            is_cet6=is_cet6,
        )

    try:
        score = float(payload.get("score_earned", 0))
    except (TypeError, ValueError):
        score = 0.0

    if is_cet6:
        score -= 1

    score = round(_clamp_band_score(score, _WRITING_BANDS), 1)
    reported_score = int(round(score * 7.1))
    comment = payload.get("comment") or f"写作得分：{score}/15（报道分：{reported_score}/106.5）。{_band_comment(score, _WRITING_BANDS)}"

    return {
        "score_earned": score,
        "reported_score": reported_score,
        "score_possible": 15.0,
        "score_possible_reported": 106.5,
        "strengths": payload.get("strengths", []),
        "issues": payload.get("issues", []),
        "suggestions": payload.get("suggestions", []),
        "comment": comment,
        "word_count": len(user_answer.split()),
    }


def _ai_score_translation(
    *,
    user_answer: str,
    reference_answer: str,
    is_cet6: bool,
) -> Dict[str, Any]:
    if not user_answer or user_answer.strip() == "":
        return score_translation_cet46(
            user_answer=user_answer,
            reference_answer=reference_answer,
            is_cet6=is_cet6,
        )
    if not check_ai():
        return score_translation_cet46(
            user_answer=user_answer,
            reference_answer=reference_answer,
            is_cet6=is_cet6,
        )

    level = "CET6" if is_cet6 else "CET4"
    prompt = _build_translation_prompt(
        level=level,
        reference=reference_answer,
        user_answer=user_answer,
    )
    result = call_ai_full(prompt, max_retries=2, max_tokens=600, timeout=120)
    payload = _extract_json_block(result.get("content", "") if result else "")
    if not payload:
        return score_translation_cet46(
            user_answer=user_answer,
            reference_answer=reference_answer,
            is_cet6=is_cet6,
        )

    try:
        score = float(payload.get("score_earned", 0))
    except (TypeError, ValueError):
        score = 0.0

    if is_cet6:
        score -= 1

    score = round(_clamp_band_score(score, _TRANSLATION_BANDS), 1)
    reported_score = int(round(score * 7.1))
    comment = payload.get("comment") or f"翻译得分：{score}/15（报道分：{reported_score}/106.5）。{_band_comment(score, _TRANSLATION_BANDS)}"

    return {
        "score_earned": score,
        "reported_score": reported_score,
        "score_possible": 15.0,
        "score_possible_reported": 106.5,
        "strengths": payload.get("strengths", []),
        "issues": payload.get("issues", []),
        "suggestions": payload.get("suggestions", []),
        "comment": comment,
    }


# ==============================================================================
# 主观题批改入口
# ==============================================================================

def grade_subjective_exam(
    exam_id: int,
    paper: Dict[str, Any],
    answers: Dict[str, Any],
    user_id: Optional[int] = None,
    db = None,
) -> Dict[str, Any]:
    """主观题批改入口（写作 + 翻译）"""
    results = []
    
    for section in paper.get("sections", []):
        for question in section.get("questions", []):
            qid = question.get("question_id") or question.get("id")
            if not qid:
                continue
            
            user_ans = answers.get(str(qid), "")
            if not user_ans:
                continue
            
            q_type = question.get("question_type") or question.get("type")
            ref_ans = question.get("reference_answer") or question.get("correct_answer") or ""
            
            word_limit = question.get("word_limit", "120-180")
            try:
                if "-" in str(word_limit):
                    word_min, word_max = map(int, word_limit.split("-"))
                else:
                    word_min, word_max = 120, 180
            except:
                word_min, word_max = 120, 180
            
            level = paper.get("paper_info", {}).get("level", "CET4")
            is_cet6 = level == "CET6"
            
            if q_type in ["writing", "essay"]:
                score_result = _ai_score_writing(
                    user_answer=user_ans,
                    reference=ref_ans,
                    word_min=word_min,
                    word_max=word_max,
                    is_cet6=is_cet6,
                )
            elif q_type == "translation":
                score_result = _ai_score_translation(
                    user_answer=user_ans,
                    reference_answer=ref_ans,
                    is_cet6=is_cet6,
                )
            else:
                continue
            
            # ========== 修改这里：同时保存原始分和报道分 ==========
            results.append({
                "question_id": str(qid),
                "question_type": q_type,
                "raw_score": score_result["score_earned"],        # 原始分 0-15
                "reported_score": score_result["reported_score"], # 报道分 0-106.5 ✅ 新增
                "score_possible": 15.0,
                "score_possible_reported": 106.5,
                "comment": score_result["comment"],
                "strengths": score_result.get("strengths", []),
                "issues": score_result.get("issues", []),
                "suggestions": score_result.get("suggestions", [])
            })
    
    return {
        "feedbacks": results,
        "total_raw_score": sum(r["raw_score"] for r in results),
        "total_reported_score": sum(r["reported_score"] for r in results)  # ✅ 新增
    }
