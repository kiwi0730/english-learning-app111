"""AI 出卷与答案生成流程。"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from utils.call_ai import call_ai_full, check_ai
from utils.database import db
from utils.exam_ai_parser import extract_json_payload, parse_exam_section_response
from utils.exam_prompts import (
    _build_answers_prompt,
    _build_banked_cloze_prompt,
    _build_close_reading_prompt,
    _build_long_reading_prompt,
    _build_translation_prompt,
    _build_writing_prompt,
)
from utils.exam_schema import build_exam_paper, count_questions, normalize_level
from utils.personalized_exam_prompts import (
    build_personalized_banked_cloze_prompt,
    build_personalized_close_reading_prompt,
    build_personalized_long_reading_prompt,
    build_personalized_translation_prompt,
    build_personalized_writing_prompt,
)

logger = logging.getLogger(__name__)


def _merge_answers_into_paper(paper: dict, answer_key: dict, analysis_key: dict) -> dict:
    for section in paper.get("sections", []):
        if not isinstance(section, dict):
            continue
        for question in section.get("questions", []):
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("question_id"))
            if question_id in answer_key and answer_key[question_id] is not None:
                question["correct_answer"] = answer_key[question_id]
            if question_id in analysis_key and analysis_key[question_id] is not None:
                question["explanation"] = analysis_key[question_id]
    paper["answer_key"] = answer_key
    paper["analysis_key"] = analysis_key
    return paper


def _merge_answers_payload_into_paper(paper: dict, answers_payload: dict) -> dict:
    answers = answers_payload.get("answers") if isinstance(answers_payload, dict) else {}
    if not isinstance(answers, dict):
        answers = {}

    normalized_answer_key = {}
    normalized_analysis_key = {}

    for section in paper.get("sections", []):
        if not isinstance(section, dict):
            continue
        for question in section.get("questions", []):
            if not isinstance(question, dict):
                continue

            question_id = str(question.get("question_id"))
            answer_entry = answers.get(question_id)
            if isinstance(answer_entry, dict):
                correct_answer = answer_entry.get("correct_answer", answer_entry.get("answer", answer_entry.get("value", "")))
                explanation = answer_entry.get("explanation", answer_entry.get("analysis", ""))
            else:
                correct_answer = answer_entry
                explanation = ""

            if correct_answer is not None:
                question["correct_answer"] = correct_answer
                normalized_answer_key[question_id] = correct_answer
            if explanation is not None:
                question["explanation"] = explanation
                normalized_analysis_key[question_id] = explanation

    paper["answer_key"] = normalized_answer_key
    paper["analysis_key"] = normalized_analysis_key
    return paper


def _generate_pipeline_exam(
    level,
    difficulty,
    words,
    section_jobs,
    paper_name: str,
    exam_type: str,
    generation_mode: str = "ai",
):
    if not check_ai() or not words:
        return None

    results = {}
    errors = []
    lock = threading.Lock()

    def generate_section(section_id, section_name, prompt_builder, max_tokens, timeout):
        try:
            prompt = prompt_builder(level, words)
            result = call_ai_full(prompt, max_retries=2, max_tokens=max_tokens, timeout=timeout)
            if not result or result.get("status") != "success":
                logger.error("AI section call failed: %s (%s)", section_id, result)
                with lock:
                    errors.append(section_id)
                return

            parsed = parse_exam_section_response(
                result.get("content", ""),
                default_section_id=section_id,
                default_section_name=section_name,
                default_section_type=section_id if not section_id.startswith("close_reading") else "close_reading",
            )

            if not parsed or not parsed.get("section"):
                content = result.get("content", "")
                snippet = content[:500] if isinstance(content, str) else str(content)[:500]
                logger.error(
                    "AI section parse failed: %s | length=%s | head=%s",
                    section_id,
                    len(content) if isinstance(content, str) else "n/a",
                    snippet,
                )
                with lock:
                    errors.append(section_id)
                return

            with lock:
                results[section_id] = {
                    "sections": [parsed.get("section")],
                    "answer_key": parsed.get("answer_key", {}),
                    "analysis_key": parsed.get("analysis_key", {}),
                }
        except Exception as exc:
            logger.error("AI section generation error: %s (%s)", section_id, str(exc))
            with lock:
                errors.append(section_id)

    threads = []
    for index, (section_id, section_name, prompt_builder, max_tokens, timeout) in enumerate(section_jobs):
        if index > 0:
            time.sleep(1)
        thread = threading.Thread(
            target=generate_section,
            args=(section_id, section_name, prompt_builder, max_tokens, timeout),
            daemon=True,
        )
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    if errors or len(results) != len(section_jobs):
        logger.error("Some sections failed to generate: %s", errors or results.keys())
        return None

    sections = []
    answer_key = {}
    analysis_key = {}

    for section_id, _, _, _, _ in section_jobs:
        if section_id in results:
            sections.extend(results[section_id]["sections"])
            answer_key.update(results[section_id]["answer_key"])
            analysis_key.update(results[section_id]["analysis_key"])

    paper = build_exam_paper(
        paper_name=paper_name,
        level=level,
        difficulty=difficulty,
        sections=sections,
        answer_key=answer_key,
        analysis_key=analysis_key,
        generation_mode=generation_mode,
        include_listening=False,
        exam_type=exam_type,
        word_count=len(words),
        word_bank_sample=words,
        submission_status="draft",
        extra_paper_info={"question_count": count_questions(sections)},
    )
    return paper


def _build_answers_payload_sync(paper: dict) -> dict:
    if not check_ai():
        raise RuntimeError("AI 接口不可用，无法生成答案")

    prompt = _build_answers_prompt(paper)
    result = call_ai_full(prompt, max_retries=2, max_tokens=2400, timeout=300)
    if not result or result.get("status") != "success":
        raise RuntimeError(f"AI 答案调用失败: {result}")

    payload = extract_json_payload(result.get("content", ""))
    if not payload:
        raise RuntimeError("AI 答案解析失败")

    answers_payload = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
    answer_key = payload.get("answer_key") if isinstance(payload.get("answer_key"), dict) else {}
    analysis_key = payload.get("analysis_key") if isinstance(payload.get("analysis_key"), dict) else {}

    if not answers_payload and not answer_key and not analysis_key:
        raise RuntimeError("AI 未返回答案与解析")

    if not answers_payload:
        answers_payload = {
            question_id: {
                "correct_answer": answer_key.get(question_id, ""),
                "explanation": analysis_key.get(question_id, ""),
            }
            for question_id in set(answer_key) | set(analysis_key)
        }

    payload["answers"] = answers_payload
    return payload


def generate_exam(
    level,
    difficulty,
    words,
    exam_type: str,
    generation_mode: str = "ai",
    **kwargs
):
    """统一的出卷函数，根据 exam_type 决定使用哪套prompts和section结构。"""
    if exam_type == "normal_exam":
        # 正常出卷的 prompts和section_jobs
        section_jobs = [
            ("writing", "Part I Writing", _build_writing_prompt, 1800, 240),
            ("translation", "Part III Translation", _build_translation_prompt, 1800, 240),
            ("banked_cloze", "Section A Banked Cloze", lambda lvl, w: _build_banked_cloze_prompt(lvl, difficulty, w), 2600, 360),
            ("long_reading", "Section B Long Reading", lambda lvl, w: _build_long_reading_prompt(lvl, difficulty, w), 5200, 600),
            ("close_reading_1", "Section C Close Reading 1", lambda lvl, w: _build_close_reading_prompt(lvl, 1, difficulty, w), 2600, 360),
            ("close_reading_2", "Section C Close Reading 2", lambda lvl, w: _build_close_reading_prompt(lvl, 2, difficulty, w), 2600, 360),
        ]
        paper_name = f"{normalize_level(level)} 正式模拟试卷"
    elif exam_type == "personalized_exam":
        # 个性化出卷的 prompts和section_jobs
        recent_scores = kwargs.get("recent_scores", [])
        wrong_words = kwargs.get("wrong_words", [])
        recommended_difficulty = kwargs.get("recommended_difficulty", difficulty)
        recent_n = kwargs.get("recent_n", 5)
        section_jobs = [
            ("writing", "Part I Writing", lambda lvl, w: build_personalized_writing_prompt(lvl, w, recent_scores, wrong_words, recommended_difficulty, recent_n), 1800, 240),
            ("translation", "Part III Translation", lambda lvl, w: build_personalized_translation_prompt(lvl, w, recent_scores, wrong_words, recommended_difficulty, recent_n), 1800, 240),
            ("banked_cloze", "Section A Banked Cloze", lambda lvl, w: build_personalized_banked_cloze_prompt(lvl, w, recent_scores, wrong_words, recommended_difficulty, recent_n), 2600, 360),
            ("long_reading", "Section B Long Reading", lambda lvl, w: build_personalized_long_reading_prompt(lvl, w, recent_scores, wrong_words, recommended_difficulty, recent_n), 5200, 600),
            ("close_reading_1", "Section C Close Reading 1", lambda lvl, w: build_personalized_close_reading_prompt(lvl, 1, w, recent_scores, wrong_words, recommended_difficulty, recent_n), 2600, 360),
            ("close_reading_2", "Section C Close Reading 2", lambda lvl, w: build_personalized_close_reading_prompt(lvl, 2, w, recent_scores, wrong_words, recommended_difficulty, recent_n), 2600, 360),
        ]
        paper_name = f"{normalize_level(level)} 个性化模拟试卷"
    else:
        raise ValueError(f"Unsupported exam_type: {exam_type}")

    return _generate_pipeline_exam(
        level=level,
        difficulty=difficulty,
        words=words,
        section_jobs=section_jobs,
        paper_name=paper_name,
        exam_type=exam_type,
        generation_mode=generation_mode,
    )


def generate_answers_async(exam_id: int, paper: dict) -> None:
    def task() -> None:
        try:
            payload = _build_answers_payload_sync(paper)

            paper_copy = json.loads(json.dumps(paper, ensure_ascii=False))
            _merge_answers_payload_into_paper(paper_copy, payload)

            paper_info = paper_copy.setdefault("paper_info", {})
            paper_info["answers_status"] = "ready"
            paper_info["answers_generated_at"] = datetime.now().isoformat(timespec="seconds")
            paper_info.pop("answers_error", None)

            db.update_exam_paper(
                exam_id,
                level=paper_info.get("level", "CET4"),
                paper_json=paper_copy,
                answers_json=payload,
                feedback_json=None,
            )
        except Exception as exc:
            logger.exception("Answer generation failed: %s", exc)
            paper_copy = json.loads(json.dumps(paper, ensure_ascii=False))
            paper_info = paper_copy.setdefault("paper_info", {})
            paper_info["answers_status"] = "failed"
            paper_info["answers_error"] = str(exc)
            db.update_exam_paper(
                exam_id,
                level=paper_info.get("level", "CET4"),
                paper_json=paper_copy,
                answers_json={"status": "failed", "error": str(exc)},
                feedback_json=None,
            )

    threading.Thread(target=task, daemon=True).start()


def generate_answers_sync(paper: dict) -> tuple:
    """同步生成答案与解析，返回 (payload, paper_with_answers)。"""
    payload = _build_answers_payload_sync(paper)
    paper_copy = json.loads(json.dumps(paper, ensure_ascii=False))
    _merge_answers_payload_into_paper(paper_copy, payload)
    paper_info = paper_copy.setdefault("paper_info", {})
    paper_info["answers_status"] = "ready"
    paper_info["answers_generated_at"] = datetime.now().isoformat(timespec="seconds")
    paper_info.pop("answers_error", None)
    return payload, paper_copy