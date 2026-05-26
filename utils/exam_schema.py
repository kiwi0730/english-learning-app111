"""试卷 JSON 公共 schema。

这里统一定义试卷、答案、解析、提交、题目结果的基础结构，
供正常出卷、历史回顾、个性化出卷等模块复用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


SECTION_SCORE_RULES = {
    "writing": {"total_score": 106.5, "question_count": 1},
    "translation": {"total_score": 106.5, "question_count": 1},
    "banked_cloze": {"total_score": 35.5, "question_count": 10},
    "long_reading": {"total_score": 71.0, "question_count": 10},
    "close_reading": {"total_score": 71.0, "question_count": 5},
}


def get_section_score_rule(section_type: Any) -> Dict[str, float]:
    """获取题型对应的固定分值规则。"""
    rule = SECTION_SCORE_RULES.get(str(section_type or "").strip())
    if rule:
        return dict(rule)
    return {"total_score": 0.0, "question_count": 0}


def get_question_score(section_type: Any, question_count: int = 0) -> float:
    """获取某题型的单题分值；没有固定规则时返回 0。"""
    rule = get_section_score_rule(section_type)
    total_score = float(rule.get("total_score", 0) or 0)
    expected_count = int(rule.get("question_count", 0) or 0)
    if total_score > 0 and expected_count > 0:
        return total_score / expected_count
    if total_score > 0 and question_count > 0:
        return total_score / question_count
    return 0.0


def normalize_level(level: Any) -> str:
    """统一级别命名为 CET4 / CET6。"""
    value = str(level or "CET4").strip().upper()
    if value in {"4", "CET-4", "CET4"}:
        return "CET4"
    if value in {"6", "CET-6", "CET6"}:
        return "CET6"
    return "CET4"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_submission(
    status: str,
    answers: Optional[Dict[str, Any]] = None,
    *,
    timestamp_key: Optional[str] = None,
    timestamp_value: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造 submission 结构。"""
    payload: Dict[str, Any] = {"status": status}
    if answers is not None:
        payload["answers"] = answers
    if timestamp_key is None:
        timestamp_key = "saved_at" if status == "draft" else "submitted_at"
    if timestamp_key:
        payload[timestamp_key] = timestamp_value or now_iso()
    if extra:
        payload.update(extra)
    return payload


def build_answers_payload(status: str, answers: Dict[str, Any]) -> Dict[str, Any]:
    """构造答案保存结构。"""
    return build_submission(status, answers, timestamp_key="saved_at" if status == "draft" else "submitted_at")


def build_question_result(
    question_id: Any,
    *,
    section_id: Any = None,
    question_type: str = "",
    user_answer: Any = "",
    correct_answer: Any = "",
    explanation: str = "",
    is_correct: Optional[bool] = None,
    score_earned: float = 0,
    grading_status: str = "pending",
) -> Dict[str, Any]:
    """构造题目结果结构。"""
    return {
        "question_id": str(question_id),
        "section_id": section_id,
        "question_type": question_type,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "explanation": explanation,
        "is_correct": is_correct,
        "score_earned": score_earned,
        "grading_status": grading_status,
    }


def count_questions(sections: Iterable[Dict[str, Any]]) -> int:
    """统计 sections 中的问题数量。"""
    total = 0
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        total += len(section.get("questions", []))
    return total


def build_exam_paper(
    *,
    paper_name: str,
    level: Any,
    difficulty: int,
    sections: List[Dict[str, Any]],
    answer_key: Optional[Dict[str, Any]] = None,
    analysis_key: Optional[Dict[str, Any]] = None,
    generation_mode: str = "ai",
    include_listening: bool = False,
    exam_type: str = "normal_exam",
    word_count: int = 0,
    word_bank_sample: Optional[List[Dict[str, Any]]] = None,
    submission_status: str = "draft",
    submission_extra: Optional[Dict[str, Any]] = None,
    extra_paper_info: Optional[Dict[str, Any]] = None,
    extra_root: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造统一试卷 JSON。"""
    normalized_level = normalize_level(level)
    answer_key = answer_key or {}
    analysis_key = analysis_key or {}
    paper_info = {
        "paper_name": paper_name,
        "exam_type": exam_type,
        "level": normalized_level,
        "difficulty": difficulty,
        "word_count": word_count,
        "word_bank_sample": word_bank_sample or [],
        "generated_at": now_iso(),
        "generation_mode": generation_mode,
        "section_count": len(sections),
        "include_listening": include_listening,
        "question_count": count_questions(sections),
    }
    if extra_paper_info:
        paper_info.update(extra_paper_info)

    paper = {
        "paper_info": paper_info,
        "sections": sections,
        "answer_key": answer_key,
        "analysis_key": analysis_key,
        "submission": build_submission(submission_status, extra=submission_extra),
    }
    if extra_root:
        paper.update(extra_root)
    return paper


def normalize_exam_paper(paper: Any) -> Dict[str, Any]:
    """把旧的或半成品 paper 归一成标准结构。"""
    if not isinstance(paper, dict):
        paper = {}
    sections = paper.get("sections") if isinstance(paper.get("sections"), list) else []
    paper_info = paper.get("paper_info") if isinstance(paper.get("paper_info"), dict) else {}
    answer_key = paper.get("answer_key") if isinstance(paper.get("answer_key"), dict) else {}
    analysis_key = paper.get("analysis_key") if isinstance(paper.get("analysis_key"), dict) else {}
    submission = paper.get("submission") if isinstance(paper.get("submission"), dict) else build_submission("draft")

    paper_info.setdefault("paper_name", "未命名试卷")
    paper_info.setdefault("exam_type", "normal_exam")
    paper_info.setdefault("level", "CET4")
    paper_info.setdefault("difficulty", 5)
    paper_info.setdefault("word_count", 0)
    paper_info.setdefault("word_bank_sample", [])
    paper_info.setdefault("generated_at", now_iso())
    paper_info.setdefault("generation_mode", "unknown")
    paper_info.setdefault("section_count", len(sections))
    paper_info.setdefault("include_listening", False)
    paper_info.setdefault("question_count", count_questions(sections))

    normalized = dict(paper)
    normalized["paper_info"] = paper_info
    normalized["sections"] = sections
    normalized["answer_key"] = answer_key
    normalized["analysis_key"] = analysis_key
    normalized["submission"] = submission
    return normalized


def extract_question_bank(paper: Dict[str, Any]) -> List[Dict[str, Any]]:
    """拉平成题目列表。"""
    questions: List[Dict[str, Any]] = []
    for section in paper.get("sections", []):
        if not isinstance(section, dict):
            continue
        questions.extend([item for item in section.get("questions", []) if isinstance(item, dict)])
    return questions