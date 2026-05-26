"""个性化出卷页面。"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime

import streamlit as st

from utils.ai_exam_pipeline import generate_answers_sync, generate_exam
from utils.ai_grading import grade_subjective_exam
from utils.database import db

from utils.exam_schema import (
    build_answers_payload,
    build_submission,
    build_question_result,
    count_questions,
    extract_question_bank,
    normalize_level,
)
from modules.exam_common import (
    init_exam_state,
    poll_exam_status,
    render_exam_empty_notice,
    render_exam_body,
    render_exam_header,
    render_exam_status,
    render_exit_controls,
    render_generate_resume_controls,
    render_personalized_exam_header,
    render_personalized_exam_setup,
    render_personalized_recommendation,
    render_save_submit_controls,
    report_generation_error,
    resume_from_query_param,
    resume_latest_ready,
    set_generating_query_param,
)


logger = logging.getLogger(__name__)


def _normalize_answer_for_grade(value):
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        value = str(value)
    elif isinstance(value, dict):
        value = value.get("answer", value.get("value", ""))
    elif isinstance(value, list):
        value = " ".join(str(item) for item in value)
    text = str(value).strip()
    text = text.replace("Ａ", "A").replace("Ｂ", "B").replace("Ｃ", "C").replace("Ｄ", "D")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    text = text.lower()

    # 处理带选项字母和选项内容的答案，如 "B. ..."、"C) ..."
    match = re.match(r"^([abcd])(?:[.)].*)?$", text)
    if match:
        return match.group(1)
    return text


def _grade_objective_exam(exam_id, paper, answers, user_id=None):
    if not isinstance(paper, dict):
        raise ValueError("paper 必须是字典")
    if not isinstance(answers, dict):
        answers = {}

    user_answers = answers.get("answers") if isinstance(answers.get("answers"), dict) else answers
    if not isinstance(user_answers, dict):
        user_answers = {}

    objective_types = {"banked_cloze", "long_reading", "close_reading"}
    subjective_types = {"writing", "translation"}

    # ========== 1. 客观题批改 ==========
    question_results = []
    objective_score = 0
    objective_total = 0
    objective_correct_count = 0
    reading_score = 0
    reading_total = 0

    for section in paper.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_id = section.get("section_id")
        section_type = section.get("section_type", "")

        for question in section.get("questions", []):
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("question_id"))
            question_type = str(question.get("question_type") or section_type or "")
            correct_answer = question.get("correct_answer")
            if correct_answer is None:
                correct_answer = question.get("reference_answer", "")
            explanation = question.get("explanation") or question.get("analysis") or ""
            user_answer = user_answers.get(question_id, "")
            score = float(question.get("score", 0) or 0)

            is_subjective = question_type in subjective_types
            is_objective = (question_type in objective_types) or bool(question.get("options"))

            is_correct = None
            score_earned = 0
            grading_status = "rule" if is_objective and not is_subjective else "pending"
            ai_feedback = None

            if is_objective and not is_subjective:
                objective_total += score
                normalized_user = _normalize_answer_for_grade(user_answer)
                normalized_correct = _normalize_answer_for_grade(correct_answer)
                is_correct = normalized_user == normalized_correct and normalized_correct != ""
                score_earned = score if is_correct else 0
                objective_score += score_earned
                if is_correct:
                    objective_correct_count += 1
                grading_status = "graded"

                if section_type in ["reading", "close_reading", "long_reading"]:
                    reading_total += score
                    if is_correct:
                        reading_score += score_earned
            else:
                # 对于主观题，暂时设置分数为0，等待AI批改
                score_earned = 0
                grading_status = "pending"

            question_results.append(
                build_question_result(
                    question_id,
                    section_id=section_id,
                    question_type=question_type,
                    user_answer=user_answer,
                    correct_answer=correct_answer,
                    explanation=explanation,
                    is_correct=is_correct,
                    score_earned=score_earned,
                    grading_status=grading_status,
                )
            )

    # ========== 2. 主观题批改（写作和翻译） ==========
    subjective_result = grade_subjective_exam(
        exam_id=exam_id,
        paper=paper,
        answers=user_answers,
        user_id=user_id,
        db=db,
    )

    # 更新question_results中的主观题分数和反馈
    feedback_by_id = {
        str(item.get("question_id")): item
        for item in subjective_result.get("feedbacks", [])
        if item.get("question_id") is not None
    }

    # 更新question_results中主观题的分数和反馈
    for qr in question_results:
        qid = qr["question_id"]
        if qid in feedback_by_id:
            feedback = feedback_by_id[qid]
            # 使用报道分作为最终得分
            qr["score_earned"] = feedback.get("reported_score", 0)
            qr["grading_status"] = "ai"
            qr["ai_feedback"] = feedback

    # 从subjective_result获取写作和翻译的总分（报道分）
    writing_reported = 0
    translation_reported = 0
    writing_possible = 0
    translation_possible = 0

    for feedback in subjective_result.get("feedbacks", []):
        q_type = feedback.get("question_type")
        if q_type in ["writing", "essay"]:
            writing_reported += feedback.get("reported_score", 0)
            writing_possible += 106.5  # 每道写作题满分为106.5报道分
        elif q_type == "translation":
            translation_reported += feedback.get("reported_score", 0)
            translation_possible += 106.5  # 每道翻译题满分为106.5报道分

    # 保存题目结果到数据库
    db.save_question_results(exam_id, question_results)
    
    # 保存总分到数据库（包含客观题和主观题分数）
    paper_user_id = user_id if user_id is not None else paper.get("user_id")
    paper_level = paper.get("paper_info", {}).get("level", paper.get("level", "CET4"))
    score_id = db.save_score(
        user_id=paper_user_id,
        level=paper_level,
        total_score=float(objective_score + writing_reported + translation_reported),
        total_possible=float(objective_total + writing_possible + translation_possible),
        exam_id=exam_id,
        reading_score=float(reading_score),
        reading_possible=float(reading_total),
        translation_score=float(translation_reported),  # 存储报道分
        translation_possible=float(translation_possible),
        writing_score=float(writing_reported),  # 存储报道分
        writing_possible=float(writing_possible),
    )

    submission_summary = {
        "status": "graded",
        "graded_at": datetime.now().isoformat(timespec="seconds"),
        "objective_score": objective_score,
        "objective_total": objective_total,
        "objective_correct_count": objective_correct_count,
        "reading_score": reading_score,
        "reading_total": reading_total,
        "translation_score": translation_reported,  # 报道分
        "translation_total": translation_possible,
        "writing_score": writing_reported,  # 报道分
        "writing_total": writing_possible,
        "score_id": score_id,
        "question_results": question_results,
        "subjective_feedback": subjective_result,
    }
    paper_copy = dict(paper)
    paper_copy["submission"] = submission_summary
    db.update_exam_paper(
        exam_id,
        paper_json=paper_copy,
        status="graded",
    )
    return submission_summary


def _calculate_adaptive_difficulty(recent_scores, standard_p: float = 0.7) -> float:
    if not recent_scores:
        return standard_p

    total_delta = 0.0
    valid_count = 0

    for score in recent_scores:
        total_possible = score.get("total_possible")
        total_score = score.get("total_score")
        if not total_possible or total_possible <= 0:
            continue

        difficulty_value = score.get("difficulty")
        try:
            p_i = float(difficulty_value)
        except (TypeError, ValueError):
            p_i = standard_p

        if p_i >= 1:
            p_i = (11 - p_i) / 10.0

        p_i = max(0.1, min(1.0, p_i))
        accuracy = float(total_score) / float(total_possible)
        total_delta += (p_i - accuracy)
        valid_count += 1

    if valid_count == 0:
        return standard_p

    p_prime = standard_p + total_delta / valid_count
    p_prime = round(p_prime, 1)
    return max(0.1, min(1.0, p_prime))


def personalized_exam(user_id, username):
    """个性化出卷页面。"""
    prefix = "personalized_exam_v2"
    init_exam_state(prefix)
    resume_from_query_param(prefix, user_id)
    render_personalized_exam_header(user_id, username)
    level, recent_n, wrong_word_count = render_personalized_exam_setup(prefix)

    recent_scores = db.get_recent_scores(user_id, normalize_level(level), recent_n)
    recommended_difficulty = _calculate_adaptive_difficulty(recent_scores)
    if not recent_scores:
        recommended_difficulty = 0.7
    render_personalized_recommendation(recent_scores, recent_n, recommended_difficulty)

    generate_clicked, resume_clicked = render_generate_resume_controls(prefix, "生成个性化试卷")
    if resume_clicked:
        resume_latest_ready(user_id, "personalized_exam", prefix)

    if generate_clicked:
        wrong_words = db.get_wrong_words(user_id, normalize_level(level))
        if wrong_words:
            # 从所有错词中随机选择指定数量
            import random
            if len(wrong_words) <= wrong_word_count:
                # 如果错词总数少于或等于所需数量，直接使用所有错词
                wrong_words = wrong_words
            else:
                # 为了兼顾高频错词和随机性，选择前2倍数量的高频错词，再从中随机选取
                top_wrong_words = wrong_words[:wrong_word_count * 2]
                wrong_words = random.sample(top_wrong_words, wrong_word_count)

        words = db.get_words_by_difficulty(level, recommended_difficulty, 50)
        if not words:
            report_generation_error(prefix, "生成失败：数据库里没有取到可用单词", "数据库里没有取到可用单词")
        else:
            paper_info = {
                "paper_name": f"{normalize_level(level)} 个性化模拟试卷",
                "exam_type": "personalized_exam",
                "level": normalize_level(level),
                "difficulty": recommended_difficulty,
                "word_count": 50,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "generation_mode": "personalized",
                "section_count": 0,
                "include_listening": False,
                "question_count": 0,
                "answers_status": "generating",
                "recent_n": recent_n,
                "recommended_difficulty": recommended_difficulty,
                "wrong_word_count": len(wrong_words),
            }
            pending_paper = {
                "paper_info": paper_info,
                "sections": [],
                "answer_key": {},
                "analysis_key": {},
                "submission": build_submission("draft", extra={"question_count": 0}),
            }
            exam_id = db.save_exam_paper(
                user_id,
                paper_info.get("level", normalize_level(level)),
                pending_paper,
                answers_json=build_answers_payload("draft", {}),
            )
            db.update_exam_paper(exam_id, status="processing")
            set_generating_query_param(exam_id)

            st.session_state[f"{prefix}_paper"] = None
            st.session_state[f"{prefix}_exam_id"] = exam_id
            st.session_state[f"{prefix}_answers"] = {}
            st.session_state[f"{prefix}_result"] = None
            st.session_state[f"{prefix}_processing"] = True
            st.session_state[f"{prefix}_status"] = f"生成中，exam_id = {exam_id}"

            def _background_generate() -> None:
                try:
                    paper = generate_exam(
                        level=level,
                        difficulty=recommended_difficulty,
                        words=words,
                        exam_type="personalized_exam",
                        generation_mode="personalized",
                        recent_scores=recent_scores,
                        wrong_words=wrong_words,
                        recommended_difficulty=recommended_difficulty,
                        recent_n=recent_n,
                    )
                    if not paper:
                        raise RuntimeError("个性化试卷生成失败，请重试")

                    answers_payload, paper_copy = generate_answers_sync(paper)

                    info = paper_copy["paper_info"]
                    info["level"] = normalize_level(level)
                    info["difficulty"] = recommended_difficulty
                    info.setdefault("paper_name", f"{normalize_level(level)} 个性化模拟试卷")
                    info["word_count"] = 50
                    info["generated_at"] = datetime.now().isoformat(timespec="seconds")
                    info["include_listening"] = False
                    info["generation_mode"] = "personalized"
                    info["question_count"] = count_questions(paper.get("sections", []))
                    info["answers_status"] = "ready"
                    info["recent_n"] = recent_n
                    info["recommended_difficulty"] = recommended_difficulty
                    info["wrong_word_count"] = len(wrong_words)

                    questions = extract_question_bank(paper)
                    answers = {str(question.get("question_id")): "" for question in questions}
                    paper_copy["submission"] = build_submission("draft", answers, extra={"question_count": len(questions)})

                    db.update_exam_paper(
                        exam_id,
                        level=info.get("level", normalize_level(level)),
                        paper_json=paper_copy,
                        answers_json=answers_payload,
                        status="ready",
                    )
                except Exception as exc:
                    failed_paper = dict(pending_paper)
                    failed_info = failed_paper.setdefault("paper_info", {})
                    failed_info["answers_status"] = "failed"
                    failed_info["answers_error"] = str(exc)
                    db.update_exam_paper(
                        exam_id,
                        paper_json=failed_paper,
                        status="failed",
                    )

            threading.Thread(target=_background_generate, daemon=True).start()

    render_exam_status(prefix)

    if st.session_state.get(f"{prefix}_processing") and st.session_state.get(f"{prefix}_exam_id"):
        poll_exam_status(prefix, st.session_state.get(f"{prefix}_exam_id"))

    paper = st.session_state.get(f"{prefix}_paper")
    if not paper:
        render_exam_empty_notice()
        return

    render_exam_header(paper, level, recommended_difficulty)
    render_exam_body(paper, prefix)
    # ========== 自定义提交控件 ==========
    save_col, submit_col = st.columns(2)
    with save_col:
        if st.button("💾 保存草稿", key=f"{prefix}_save_draft"):
            submission = paper.get("submission", {})
            submission["answers"] = st.session_state.get(f"{prefix}_answers", {})
            submission["status"] = "draft"
            submission["saved_at"] = datetime.now().isoformat()
            paper["submission"] = submission
            exam_id = st.session_state.get(f"{prefix}_exam_id")
            if exam_id:
                db.update_exam_paper(exam_id, paper_json=paper)
            st.success("草稿已保存")
    
    with submit_col:
        if st.button("📝 提交批改", key=f"{prefix}_submit"):
            answers = st.session_state.get(f"{prefix}_answers", {})
            exam_id = st.session_state.get(f"{prefix}_exam_id")
            
            if not answers:
                st.warning("请先完成答题")
            else:
                with st.spinner("AI 批改中，请稍候..."):
                    # 调用批改函数
                    grading_summary = _grade_objective_exam(exam_id, paper, answers, user_id=user_id)
                    
                    # 获取各部分得分
                    objective_score = grading_summary.get("objective_score", 0)
                    objective_total = grading_summary.get("objective_total", 0)
                    writing_score = grading_summary.get("writing_score", 0)
                    translation_score = grading_summary.get("translation_score", 0)
                    writing_reported = writing_score  
                    translation_reported = translation_score
                    
                    # 保存结果到session state
                    st.session_state[f"{prefix}_result"] = grading_summary
                    st.session_state[f"{prefix}_writing_score"] = writing_score
                    st.session_state[f"{prefix}_writing_reported"] = writing_reported
                    st.session_state[f"{prefix}_translation_score"] = translation_score
                    st.session_state[f"{prefix}_translation_reported"] = translation_reported
                    
                    # 显示成功消息
                    total_score_reported = objective_score + writing_reported + translation_reported
                    st.success(f"✅ 批改完成！客观题得分 {objective_score}，写作得分 {writing_reported:.1f}，翻译得分 {translation_reported:.1f}，总分 {total_score_reported:.1f}")
                    
                    # 显示详细结果
                    st.write(f"**客观题得分：{objective_score} 分**")
                    st.write(f"**主观题得分：{writing_reported + translation_reported:.1f} 分**")
                    st.write(f"**试卷总分：{total_score_reported:.1f} 分**")
                    st.write(f"写作赋分：{writing_reported:.1f}/106.5")
                    st.write(f"翻译赋分：{translation_reported:.1f}/106.5")
                    st.write("---")
                    
                    # 显示主观题批改结果
                    st.write("### 主观题批改结果")
                    
                    # 从批改结果中获取反馈信息
                    subjective_feedback = grading_summary.get("subjective_feedback", {})
                    feedbacks = subjective_feedback.get("feedbacks", [])
                    
                    writing_feedback = ""
                    translation_feedback = ""
                    
                    for feedback in feedbacks:
                        q_type = feedback.get("question_type")
                        if q_type in ["writing", "essay"]:
                            if not writing_feedback:
                                writing_feedback = feedback.get("comment", "")
                        elif q_type == "translation":
                            if not translation_feedback:
                                translation_feedback = feedback.get("comment", "")
                    
                    if writing_feedback:
                        st.write(f"**写作**")
                        writing_raw_score = next((f.get("raw_score", 0) for f in feedbacks if f.get("question_type") in ["writing", "essay"]), 0)
                        st.write(f"  原始分：{writing_raw_score}/15")
                        st.write(f"  报道分：{writing_reported:.1f}/106.5")
                        st.write(f"  评语：{writing_feedback}")
                        st.write("")
                    
                    if translation_feedback:
                        st.write(f"**翻译**")
                        translation_raw_score = next((f.get("raw_score", 0) for f in feedbacks if f.get("question_type") == "translation"), 0)
                        st.write(f"  原始分：{translation_raw_score}/15")
                        st.write(f"  报道分：{translation_reported:.1f}/106.5")
                        st.write(f"  评语：{translation_feedback}")
                        st.write("")
                    
                    # 保存到 session_state
                    st.session_state[f"{prefix}_result"] = {
                        "objective_score": objective_score,
                        "writing_score": writing_score,
                        "translation_score": translation_score,
                        "total_reported": total_score_reported
                    }
    
    # 显示提交结果摘要
    result = st.session_state.get(f"{prefix}_result")
    if result:
        # 这里不再显示完整的JSON结果
        pass
    
    exam_id = st.session_state.get(f"{prefix}_exam_id")
    if exam_id is not None:
        st.success(f"最近一次保存/提交的试卷ID：{exam_id}")
    
    render_exit_controls(prefix)