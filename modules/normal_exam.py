"""正常出卷页面。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

import streamlit as st

from utils.ai_exam_pipeline import generate_exam, generate_answers_sync
from utils.call_ai import check_ai
from utils.database import db
from utils.ai_grading import grade_subjective_exam

from utils.exam_schema import (
    build_answers_payload,
    build_submission,
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
    render_normal_exam_header,
    render_normal_exam_setup,
    report_generation_error,
    resume_from_query_param,
    resume_latest_ready,
    set_generating_query_param,
)

logger = logging.getLogger(__name__)


# ========== 客观题批改函数（自己实现，不依赖 personalized_exam） ==========
def _grade_objective_exam(paper: dict, answers: dict) -> dict:
    """客观题批改函数"""
    total_score = 0
    correct_count = 0
    total_questions = 0
    total_possible = 0
    
    for section in paper.get("sections", []):
        for question in section.get("questions", []):
            qid = question.get("question_id")
            q_type = question.get("question_type") or question.get("type")
            
            # 只批改客观题（排除写作和翻译）
            if q_type in ["writing", "essay", "translation"]:
                continue
            
            total_questions += 1
            total_possible += question.get("score", 1)
            
            if qid and str(qid) in answers:
                user_answer = answers.get(str(qid), "")
                correct_answer = question.get("correct_answer") or question.get("answer") or question.get("reference_answer", "")
                
                # 比较答案（忽略大小写和前后空格）
                if user_answer and user_answer.upper().strip() == correct_answer.upper().strip():
                    score = question.get("score", 1)
                    total_score += score
                    correct_count += 1
    
    return {
        "score": total_score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "total_possible": total_possible,
    }


def normal_exam(user_id, username):
    """正常出卷页面。"""
    prefix = "normal_exam_v2"
    init_exam_state(prefix)
    resume_from_query_param(prefix, user_id)
    ai_available = check_ai()
    render_normal_exam_header(user_id, username, ai_available)
    level, difficulty = render_normal_exam_setup(prefix)

    generate_clicked, resume_clicked = render_generate_resume_controls(prefix, "生成试卷")
    if resume_clicked:
        resume_latest_ready(user_id, "normal_exam", prefix)

    if generate_clicked:
        if not ai_available:
            report_generation_error(prefix, "生成失败：AI 出题接口不可用", "AI 出题接口不可用")
        else:
            words = db.get_words_by_difficulty(level, difficulty, 50)
            if not words:
                report_generation_error(prefix, "生成失败：数据库里没有取到可用单词", "数据库里没有取到可用单词")
            else:
                paper_info = {
                    "paper_name": f"{normalize_level(level)} 正式模拟试卷",
                    "exam_type": "normal_exam",
                    "level": normalize_level(level),
                    "difficulty": difficulty,
                    "word_count": 50,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "generation_mode": "ai",
                    "section_count": 0,
                    "include_listening": False,
                    "question_count": 0,
                    "answers_status": "generating",
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
                            difficulty=difficulty,
                            words=words,
                            exam_type="normal_exam",
                            generation_mode="ai",
                        )
                        if not paper:
                            raise RuntimeError("AI 试卷生成失败，请重试")

                        answers_payload, paper_copy = generate_answers_sync(paper)

                        info = paper_copy["paper_info"]
                        info["level"] = normalize_level(level)
                        info["difficulty"] = difficulty
                        info.setdefault("paper_name", f"{normalize_level(level)} 正式模拟试卷")
                        info["word_count"] = 50
                        info["generated_at"] = datetime.now().isoformat(timespec="seconds")
                        info["include_listening"] = False
                        info["generation_mode"] = "ai"
                        info["question_count"] = count_questions(paper.get("sections", []))
                        info["answers_status"] = "ready"

                        questions = extract_question_bank(paper)
                        answers = {str(question.get("question_id")): "" for question in questions}
                        paper_copy["submission"] = build_submission("draft", answers, extra={"question_count": len(questions)})

                        # ========== 强制设置写作题目 ==========
                        import random
                        writing_topics = {
                            "CET4": [
                                "The Importance of Developing Healthy Lifestyle Habits Among College Students",
                                "The Impact of Social Media on Interpersonal Communication",
                                "How to Balance Academic Study and Extracurricular Activities",
                                "The Role of Critical Thinking in the Age of Information",
                                "Ways to Bridge the Generation Gap Between Parents and Children",
                                "The Benefits of Learning a Second Language",
                                "How to Deal with Stress in College Life",
                                "The Importance of Time Management for College Students",
                            ],
                            "CET6": [
                                "The Ethical Implications of Artificial Intelligence in Modern Society",
                                "How to Balance Economic Development and Environmental Protection",
                                "The Importance of Cultural Heritage Preservation in Globalization",
                                "The Role of Innovation in Driving Economic Growth",
                                "Ways to Address the Challenge of an Aging Population",
                                "The Impact of Remote Work on Corporate Culture",
                                "How to Foster Creativity and Critical Thinking in Education",
                            ]
                        }
                        level_key = "CET6" if "CET6" in level else "CET4"
                        topic_list = writing_topics.get(level_key, writing_topics["CET4"])
                        selected_topic = random.choice(topic_list)
                        
                        for section in paper_copy.get("sections", []):
                            if section.get("section_type") == "writing" or section.get("section_id") == "writing":
                                for q in section.get("questions", []):
                                    if q.get("question_id") == "writing_1":
                                        q["prompt"] = f"For this part, you are allowed 30 minutes to write an essay on the topic: {selected_topic}. You should write at least 120 words but no more than 180 words."
                                        q["stem"] = "Write an essay on the following topic."

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

    render_exam_header(paper, level, difficulty)
    render_exam_body(paper, prefix)
    
    # ========== 融合批改：客观题 + 主观题 ==========
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
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
    
    with col2:
        if st.button("📝 提交批改", key=f"{prefix}_submit"):
            answers = st.session_state.get(f"{prefix}_answers", {})
            exam_id = st.session_state.get(f"{prefix}_exam_id")
            
            if not answers:
                st.warning("请先完成答题")
            else:
                with st.spinner("AI 批改中，请稍候..."):
                    # ========== 1. 客观题批改 ==========
                    objective_result = _grade_objective_exam(paper, answers)
                    objective_score = objective_result.get("score", 0)
                    objective_possible = objective_result.get("total_possible", 0)
                    
                    # ========== 2. 主观题批改（基于 question_type） ==========
                    subjective_result = grade_subjective_exam(
                        exam_id=exam_id or 0,
                        paper=paper,
                        answers=answers,
                        user_id=user_id,
                        db=db,
                    )

                    writing_score = 0
                    translation_score = 0
                    writing_reported = 0
                    translation_reported = 0
                    writing_feedback = ""
                    translation_feedback = ""

                    for feedback in subjective_result.get("feedbacks", []):
                        q_type = feedback.get("question_type")
                        if q_type in ["writing", "essay"]:
                            writing_score += feedback.get("raw_score", 0)
                            writing_reported += feedback.get("reported_score", 0)
                            if not writing_feedback:
                                writing_feedback = feedback.get("comment", "")
                        elif q_type == "translation":
                            translation_score += feedback.get("raw_score", 0)
                            translation_reported += feedback.get("reported_score", 0)
                            if not translation_feedback:
                                translation_feedback = feedback.get("comment", "")

                    st.session_state[f"{prefix}_writing_score"] = writing_score
                    st.session_state[f"{prefix}_writing_reported"] = writing_reported
                    st.session_state[f"{prefix}_writing_feedback"] = writing_feedback
                    st.session_state[f"{prefix}_translation_score"] = translation_score
                    st.session_state[f"{prefix}_translation_reported"] = translation_reported
                    st.session_state[f"{prefix}_translation_feedback"] = translation_feedback

                    feedback_by_id = {
                        str(item.get("question_id")): item
                        for item in subjective_result.get("feedbacks", [])
                        if item.get("question_id") is not None
                    }

                    question_results = []
                    for section in paper.get("sections", []):
                        if not isinstance(section, dict):
                            continue
                        section_id = section.get("section_id")
                        for question in section.get("questions", []):
                            if not isinstance(question, dict):
                                continue
                            qid = question.get("question_id")
                            if qid is None:
                                continue
                            qid_str = str(qid)
                            q_type = question.get("question_type") or question.get("type")
                            user_answer = answers.get(qid_str, "")
                            correct_answer = question.get("correct_answer", question.get("answer", ""))
                            explanation = question.get("explanation", "")
                            score_earned = 0
                            is_correct = None
                            grading_status = "ai" if q_type in ["writing", "essay", "translation"] else "rule"
                            ai_feedback = None

                            if q_type in ["writing", "essay", "translation"]:
                                feedback = feedback_by_id.get(qid_str)
                                if feedback:
                                    score_earned = feedback.get("raw_score", 0)
                                    ai_feedback = feedback
                            else:
                                if user_answer and str(user_answer).strip() != "":
                                    is_correct = str(user_answer).upper().strip() == str(correct_answer).upper().strip()
                                    score_earned = question.get("score", 1) if is_correct else 0

                            question_results.append(
                                {
                                    "question_id": qid_str,
                                    "question_type": q_type,
                                    "section_id": section_id,
                                    "user_answer": user_answer,
                                    "correct_answer": correct_answer,
                                    "explanation": explanation,
                                    "is_correct": is_correct,
                                    "score_earned": score_earned,
                                    "grading_status": grading_status,
                                    "ai_feedback": ai_feedback,
                                }
                            )

                    # ========== 3. 计算总分 ==========
                    total_score_reported = objective_score + writing_reported + translation_reported
                    total_possible_reported = objective_possible + 106.5 + 106.5

                    # ========== 4. 保存到数据库 ==========
                    if exam_id:
                        if question_results:
                            db.save_question_results(exam_id, question_results)
                        total_possible = total_possible_reported
                        db.save_score(
                            user_id=user_id,
                            level=paper.get("paper_info", {}).get("level", normalize_level(level)),
                            total_score=total_score_reported,
                            total_possible=total_possible,
                            exam_id=exam_id,
                            reading_score=objective_score,
                            reading_possible=objective_possible,
                            translation_score=translation_reported,
                            translation_possible=106.5,
                            writing_score=writing_reported,
                            writing_possible=106.5,
                        )
                        now_ts = datetime.now().isoformat(timespec="seconds")
                        submission = paper.get("submission", {})
                        submission["answers"] = answers
                        submission["status"] = "graded"
                        submission["submitted_at"] = submission.get("submitted_at", now_ts)
                        submission["graded_at"] = now_ts
                        paper["submission"] = submission
                        db.update_exam_paper(exam_id, paper_json=paper, status="graded")

                # ========== 5. 显示批改结果 ==========
                st.success("✅ 批改完成！")
                st.write(f"**客观题得分：{objective_score} 分**")
                st.write(f"**主观题得分：{writing_reported + translation_reported:.1f} 分**")
                st.write(f"**试卷总分：{total_score_reported:.1f} 分**")
                st.write(f"写作赋分：{writing_reported:.1f}/106.5")
                st.write(f"翻译赋分：{translation_reported:.1f}/106.5")
                st.write("---")
                st.write("### 主观题批改结果")
                
                if writing_feedback:
                    st.write(f"**写作**")
                    st.write(f"  原始分：{writing_score}/15")
                    st.write(f"  报道分：{writing_reported}/106.5")
                    st.write(f"  评语：{writing_feedback}")
                    st.write("")
                
                if translation_feedback:
                    st.write(f"**翻译**")
                    st.write(f"  原始分：{translation_score}/15")
                    st.write(f"  报道分：{translation_reported}/106.5")
                    st.write(f"  评语：{translation_feedback}")
                    st.write("")
                
                st.write("---")
                
                # 保存到 session_state
                st.session_state[f"{prefix}_result"] = {
                    "objective_score": objective_score,
                    "writing_score": writing_score,
                    "translation_score": translation_score,
                    "total_reported": total_score_reported
                }
    
    with col3:
        if st.button("🗑️ 清空试卷", key=f"{prefix}_clear"):
            for key in list(st.session_state.keys()):
                if key.startswith(prefix):
                    del st.session_state[key]
            st.rerun()
    
    render_exit_controls(prefix)