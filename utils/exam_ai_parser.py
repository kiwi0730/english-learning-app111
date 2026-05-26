"""AI 试卷返回结果解析。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

try:
    from json_repair import repair_json
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False
    repair_json = None

from utils.exam_schema import build_exam_paper, get_question_score, get_section_score_rule, normalize_level

logger = logging.getLogger(__name__)


def _infer_question_score(raw_score: Any, section_total_score: Any, question_count: int) -> float:
    """推断题目分值，优先使用 AI 明确返回的分值。"""
    if raw_score is not None:
        try:
            score_value = float(raw_score)
            if score_value > 0:
                return score_value
        except (TypeError, ValueError):
            pass

    try:
        total_score = float(section_total_score or 0)
    except (TypeError, ValueError):
        total_score = 0.0

    if total_score > 0 and question_count > 0:
        inferred = total_score / question_count
        return inferred if inferred > 0 else 0.0

    return 0.0


def _escape_newlines_in_json_strings(text: str) -> str:
    output = []
    in_string = False
    escape = False
    for char in text:
        if escape:
            output.append(char)
            escape = False
            continue

        if char == "\\":
            output.append(char)
            escape = True
            continue

        if char == "\"":
            in_string = not in_string
            output.append(char)
            continue

        if in_string and char in {"\n", "\r"}:
            output.append("\\n")
            continue

        output.append(char)

    return "".join(output)


def _escape_json_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\r", "\\r").replace("\n", "\\n")


def _escape_field_by_boundary(blob: str, field_name: str, boundary_keys: List[str]) -> str:
    key_match = re.search(rf'"{re.escape(field_name)}"\s*:\s*"', blob)
    if not key_match:
        return blob

    value_start = key_match.end()
    boundary_alt = "|".join(map(re.escape, boundary_keys))
    boundary_pattern = r'"\s*,\s*"(?:' + boundary_alt + r')"|"\s*\}\s*$'
    boundary_match = re.search(boundary_pattern, blob[value_start:])
    if not boundary_match:
        return blob

    value_end = value_start + boundary_match.start()
    raw_value = blob[value_start:value_end]
    escaped_value = _escape_json_string(raw_value)
    return blob[:value_start] + escaped_value + blob[value_end:]


def _truncate_to_balanced_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None

    balance = 0
    in_string = False
    escape = False
    last_complete = None

    for index, char in enumerate(text[start:], start=start):
        if escape:
            escape = False
            continue

        if char == "\\":
            escape = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
            if balance == 0:
                last_complete = index

    if last_complete is None:
        return None

    return text[start : last_complete + 1]


def _repair_json_payload(text: str) -> Optional[Dict[str, Any]]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = text[start : end + 1]
    repaired = _escape_newlines_in_json_strings(candidate)
    boundary_keys = [
        "questions",
        "answer_key",
        "analysis_key",
        "section_id",
        "section_name",
        "section_type",
        "description",
        "total_score",
        "prompt",
        "stem",
        "options",
        "correct_answer",
        "explanation",
        "score",
    ]
    # 修复选项数组中缺少逗号的问题，如: ["A" "B", "C"] -> ["A", "B", "C"]
    # 匹配两个相邻的选项之间没有逗号的情况
    repaired = re.sub(r'("[A-Z](?:\.[^"]*)?")\s+("[A-Z](?:\.[^"]*)?")', r'\1,\2', repaired)
    repaired = re.sub(r'("[^"]+")\s+("[A-Z]")', r'\1,\2', repaired)
    
    repaired = _escape_field_by_boundary(repaired, "content", boundary_keys)
    repaired = _escape_field_by_boundary(repaired, "passage", boundary_keys)
    # 修复选项列表缺少闭合括号的问题
    # 匹配选项数组后直接跟其他字段的情况，如: "options": ["A", "B"] "score": 1
    repaired = re.sub(r'(\[\s*("[^"]*"\s*,\s*)*"[^"]*"\s*)(?=\s*,\s*"score")', r'\1]', repaired)
    repaired = re.sub(r'(\[\s*("[^"]*"\s*,\s*)*"[^"]*"\s*)(?=\s*"score")', r'\1],', repaired)
    
    # 修复选项数组后直接跟其他字段的情况（无逗号）
    repaired = re.sub(r'(\])\s*("question_id|"question_type|"stem|"prompt|"passage|"correct_answer|"explanation|"score)', r'\1,\2', repaired)
    
    repaired = _escape_field_by_boundary(repaired, "content", boundary_keys)
    repaired = _escape_field_by_boundary(repaired, "passage", boundary_keys)
    repaired = re.sub(r",\s*([}\\])", r"\1", repaired)
    repaired = re.sub(r"}\s*\"(answer_key|analysis_key|paper_info|sections)\"", r"}, \"\1\"", repaired)
    repaired = re.sub(r"}\s*\"analysis_key\"", r"}, \"analysis_key\"", repaired)

    try:
        parsed = json.loads(repaired)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        trimmed = _truncate_to_balanced_object(repaired)
        if trimmed:
            try:
                parsed = json.loads(trimmed)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def extract_json_payload(content: Any) -> Optional[Dict[str, Any]]:
    """从 AI 输出中提取 JSON 对象。"""
    if not content:
        return None

    if isinstance(content, dict):
        return content if isinstance(content, dict) else None

    text = str(content).strip()
    fenced_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S | re.I)
    if fenced_match:
        try:
            parsed = json.loads(fenced_match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            repaired = _repair_json_payload(fenced_match.group(1))
            if repaired is not None:
                logger.warning("AI JSON payload repaired after decode error")
                return repaired
            logger.error("AI JSON decode failed in fenced block")

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        
        # 尝试直接解析
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError as exc:
            logger.warning(f"JSON decode error: {exc}")
        
        # 方案1：使用自定义修复函数
        repaired = _repair_json_payload(text)
        if repaired is not None:
            logger.info("Successfully repaired JSON with custom repair function")
            return repaired
        
        # 方案2：使用 json-repair 库（后备）
        if HAS_JSON_REPAIR and repair_json:
            try:
                repaired = repair_json(candidate)
                if repaired:
                    parsed = json.loads(repaired) if isinstance(repaired, str) else repaired
                    if isinstance(parsed, dict):
                        logger.info("Successfully repaired JSON with json-repair library")
                        return parsed
            except Exception as e:
                logger.warning(f"json-repair failed: {e}")
        
        logger.error("All JSON repair attempts failed")

    return None


def _build_rendered_text(paper: Dict[str, Any]) -> str:
    paper_info = paper.get("paper_info", {}) if isinstance(paper.get("paper_info"), dict) else {}
    sections = paper.get("sections", []) if isinstance(paper.get("sections"), list) else []

    lines = [paper_info.get("paper_name", "模拟试卷"), "", "Part I Writing", ""]
    if sections:
        lines.append(sections[0].get("content", ""))
    lines.extend(["", "Part II Reading Comprehension", ""])
    for section in sections[1:4]:
        lines.append(section.get("section_name", ""))
        lines.append("")
        lines.append(section.get("content", ""))
        lines.append("")
    lines.extend(["Part III Translation", ""])
    if sections:
        lines.append(sections[-1].get("content", ""))
    return "\n".join(line for line in lines if line is not None).strip()


def parse_exam_ai_response(content: Any, level: Any, difficulty: int, words: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """把 AI 返回解析成标准试卷 JSON。"""
    payload = extract_json_payload(content)
    if not payload or not isinstance(payload.get("sections"), list):
        return None

    sections = []
    answer_key = payload.get("answer_key") if isinstance(payload.get("answer_key"), dict) else {}
    analysis_key = payload.get("analysis_key") if isinstance(payload.get("analysis_key"), dict) else {}

    for section in payload["sections"]:
        if not isinstance(section, dict):
            continue
        if section.get("section_type") == "listening":
            continue

        section_type = section.get("section_type") or "vocabulary"
        questions_raw = section.get("questions", [])
        question_count = len(questions_raw) if isinstance(questions_raw, list) else 0
        fixed_rule = get_section_score_rule(section_type)
        fixed_total_score = fixed_rule.get("total_score", 0.0)
        questions = []
        for index, item in enumerate(questions_raw, start=1):
            if not isinstance(item, dict):
                continue
            question_id = item.get("question_id") or f"{section.get('section_id', 'section')}_{index}"
            correct_answer = item.get("correct_answer", item.get("reference_answer", answer_key.get(str(question_id), "")))
            questions.append(
                {
                    "question_id": question_id,
                    "question_type": item.get("question_type") or section.get("section_type") or "vocabulary",
                    "word": item.get("word", ""),
                    "stem": item.get("stem") or item.get("prompt") or "请作答",
                    "prompt": item.get("prompt") or "请作答",
                    "passage": item.get("passage", ""),
                    "options": item.get("options", []),
                    "correct_answer": correct_answer,
                    "explanation": item.get("explanation", analysis_key.get(str(question_id), "")),
                    "score": get_question_score(section_type, question_count),
                }
            )

        if questions:
            sections.append(
                {
                    "section_id": section.get("section_id") or f"section_{len(sections) + 1}",
                    "section_name": section.get("section_name") or section.get("section_id") or "试题区块",
                    "section_type": section_type,
                    "description": section.get("description", ""),
                    "total_score": fixed_total_score or section.get("total_score", 0),
                    "questions": questions,
                }
            )

    if not sections:
        return None

    all_questions = []
    for section in sections:
        all_questions.extend(section["questions"])

    vocab_count = 0
    for section in sections:
        if section.get("section_type") == "vocabulary":
            vocab_count = len(section.get("questions", []))
            break

    paper = build_exam_paper(
        paper_name=payload.get("paper_info", {}).get("paper_name", f"{normalize_level(level)} 正式模拟试卷"),
        level=payload.get("paper_info", {}).get("level", level),
        difficulty=difficulty,
        sections=sections,
        answer_key=answer_key or {str(item["question_id"]): item.get("correct_answer", item.get("reference_answer", "")) for item in all_questions},
        analysis_key=analysis_key or {str(item["question_id"]): item.get("explanation", "") for item in all_questions},
        generation_mode="ai",
        include_listening=False,
        exam_type="normal_exam",
        word_count=vocab_count,
        word_bank_sample=words,
        submission_status="draft",
        extra_paper_info={"question_count": len(all_questions)},
    )
    paper["rendered_text"] = _build_rendered_text(paper)
    return paper


def parse_exam_section_response(
    content: Any,
    *,
    default_section_id: str,
    default_section_name: str,
    default_section_type: str,
) -> Optional[Dict[str, Any]]:
    """把 AI 返回解析成单个 section。"""
    payload = extract_json_payload(content)
    if not payload:
        return None

    section_payload = payload.get("section") if isinstance(payload.get("section"), dict) else payload
    if not isinstance(section_payload, dict):
        return None

    questions_raw = section_payload.get("questions")

    answer_key = payload.get("answer_key") if isinstance(payload.get("answer_key"), dict) else {}
    analysis_key = payload.get("analysis_key") if isinstance(payload.get("analysis_key"), dict) else {}

    questions = []
    fixed_rule = get_section_score_rule(default_section_type)
    fixed_total_score = fixed_rule.get("total_score", 0.0)
    if isinstance(questions_raw, list) and questions_raw:
        question_count = len(questions_raw)
        for index, item in enumerate(questions_raw, start=1):
            if not isinstance(item, dict):
                continue

            question_id = item.get("question_id") or f"{default_section_id}_{index}"
            correct_answer = item.get("correct_answer", item.get("reference_answer", answer_key.get(str(question_id), "")))
            explanation = item.get("explanation", analysis_key.get(str(question_id), ""))
            questions.append(
                {
                    "question_id": question_id,
                    "question_type": item.get("question_type") or default_section_type,
                    "word": item.get("word", ""),
                    "stem": item.get("stem") or item.get("prompt") or "请作答",
                    "prompt": item.get("prompt") or "请作答",
                    "passage": item.get("passage", ""),
                    "options": item.get("options", []),
                    "correct_answer": correct_answer,
                    "explanation": explanation,
                    "score": get_question_score(default_section_type, question_count),
                }
            )
            answer_key.setdefault(str(question_id), correct_answer)
            analysis_key.setdefault(str(question_id), explanation)
    else:
        fallback_keys = list(answer_key.keys()) or list(analysis_key.keys())
        fallback_count = len(fallback_keys)
        if fallback_count == 0:
            if default_section_type == "banked_cloze":
                fallback_count = 10
            elif default_section_type == "long_reading":
                fallback_count = 10
            elif default_section_type == "close_reading":
                fallback_count = 5
            else:
                fallback_count = 1

        if default_section_type == "banked_cloze":
            options = [chr(65 + idx) for idx in range(15)]
            stem = "Choose the best word to fill in the blank."
            prompt_template = "Blank {}"
        elif default_section_type == "long_reading":
            options = [chr(65 + idx) for idx in range(13)]
            stem = "Choose the paragraph that matches the statement."
            prompt_template = "Statement {}"
        elif default_section_type == "close_reading":
            options = ["A", "B", "C", "D"]
            stem = "According to the passage, ...?"
            prompt_template = "Choose the best answer."
        else:
            options = []
            stem = "请作答"
            prompt_template = "请作答"

        inferred_score = get_question_score(default_section_type, fallback_count)

        for index in range(1, fallback_count + 1):
            question_id = fallback_keys[index - 1] if index <= len(fallback_keys) else f"{default_section_id}_{index}"
            correct_answer = answer_key.get(str(question_id), "")
            explanation = analysis_key.get(str(question_id), "")
            questions.append(
                {
                    "question_id": question_id,
                    "question_type": default_section_type,
                    "word": "",
                    "stem": stem,
                    "prompt": prompt_template.format(index) if "{}" in prompt_template else prompt_template,
                    "passage": "",
                    "options": options,
                    "correct_answer": correct_answer,
                    "explanation": explanation,
                    "score": inferred_score,
                }
            )
            answer_key.setdefault(str(question_id), correct_answer)
            analysis_key.setdefault(str(question_id), explanation)

        logger.warning("AI section missing questions; synthesized fallback questions: %s", default_section_id)

    if not questions:
        return None

    section = {
        "section_id": section_payload.get("section_id", default_section_id),
        "section_name": section_payload.get("section_name", default_section_name),
        "section_type": section_payload.get("section_type", default_section_type),
        "description": section_payload.get("description", ""),
        "total_score": fixed_total_score or section_payload.get("total_score", sum(item.get("score", 0) for item in questions)),
        "questions": questions,
    }
    if section_payload.get("content"):
        section["content"] = section_payload.get("content")
        for item in section["questions"]:
            if not item.get("passage"):
                item["passage"] = section_payload.get("content")

    return {
        "section": section,
        "answer_key": answer_key,
        "analysis_key": analysis_key,
    }