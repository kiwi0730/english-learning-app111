"""
历史回顾页面
C 负责维护此文件
"""

import json

import streamlit as st
from utils.exam_schema import normalize_exam_paper
from utils.database import db


def _parse_json_field(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _build_question_row_map(question_results):
    row_map = {}
    for item in question_results or []:
        if not isinstance(item, dict):
            continue
        ai_feedback = _parse_json_field(item.get("ai_feedback"))
        if ai_feedback:
            item = dict(item)
            item["ai_feedback"] = ai_feedback
        question_id = str(item.get("question_id"))
        row_map[question_id] = item
    return row_map


def _build_question_review_rows(paper_json, question_row_map):
    rows = []
    submission = paper_json.get("submission") if isinstance(paper_json.get("submission"), dict) else {}
    submission_answers = submission.get("answers") if isinstance(submission.get("answers"), dict) else {}

    for section in paper_json.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_id = section.get("section_id")
        section_type = section.get("section_type", "")
        for question in section.get("questions", []):
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("question_id"))
            row = question_row_map.get(question_id, {})
            user_answer = row.get("user_answer", submission_answers.get(question_id, ""))
            correct_answer = row.get("correct_answer", question.get("correct_answer", ""))
            explanation = row.get("explanation", question.get("explanation", ""))
            is_correct = row.get("is_correct")
            score_earned = float(row.get("score_earned", 0) or 0)
            question_score = float(question.get("score", 0) or 0)
            ai_feedback = row.get("ai_feedback")

            rows.append(
                {
                    "section_id": section_id,
                    "section_type": section_type,
                    "question_id": question_id,
                    "question_type": question.get("question_type", section_type),
                    "score": question_score,
                    "score_earned": score_earned,
                    "is_correct": is_correct,
                    "user_answer": user_answer,
                    "correct_answer": correct_answer,
                    "explanation": explanation,
                    "ai_feedback": ai_feedback,
                }
            )

    return rows


def _build_question_map(paper_json):
    question_map = {}
    for section in paper_json.get("sections", []):
        if not isinstance(section, dict):
            continue
        for question in section.get("questions", []):
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("question_id"))
            question_map[question_id] = {
                "question": question,
                "section": section,
            }
    return question_map


def _get_question_text(question):
    for key in ("stem", "question", "text", "content", "prompt"):
        value = question.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_answer(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text.replace(" ", "").upper()


def _normalize_options(question):
    options = question.get("options")
    if isinstance(options, dict):
        items = list(options.items())
        return [(str(k), str(v)) for k, v in items]
    if isinstance(options, list):
        normalized = []
        for idx, item in enumerate(options):
            if isinstance(item, dict):
                label = item.get("label") or item.get("key") or item.get("option")
                text = item.get("text") or item.get("value") or item.get("content")
                if label is None:
                    label = chr(ord("A") + idx)
                normalized.append((str(label), str(text) if text is not None else ""))
            else:
                label = chr(ord("A") + idx)
                normalized.append((label, str(item)))
        return normalized
    return []


def _render_option(label, text, is_correct, is_user, is_user_correct, is_user_wrong):
    classes = ["option"]
    if is_correct:
        classes.append("option-correct")
    if is_user and is_user_correct:
        classes.append("option-user-correct")
    if is_user_wrong:
        classes.append("option-user-wrong")
    class_attr = " ".join(classes)
    content = f"<strong>{label}.</strong> {text}"
    if is_user_wrong and not is_correct:
        content = f"<span class=\"option-wrong-choice\">{content}</span>"
    st.markdown(f"<div class=\"{class_attr}\">{content}</div>", unsafe_allow_html=True)


def _extract_reported_score(ai_feedback, raw_score):
    if isinstance(ai_feedback, dict):
        reported = ai_feedback.get("reported_score")
        if reported is not None:
            try:
                return float(reported)
            except (TypeError, ValueError):
                pass
    try:
        return float(raw_score or 0) * 7.1
    except (TypeError, ValueError):
        return 0.0


def _simplify_feedback(ai_feedback):
    if not ai_feedback:
        return ""
    if isinstance(ai_feedback, str):
        return ai_feedback.strip()
    if isinstance(ai_feedback, dict):
        for key in ("comment", "feedback", "summary", "analysis"):
            value = ai_feedback.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    return ""


def history(user_id, username):
    """历史回顾页面"""
    st.subheader("📊 历史回顾")
    st.write(f"当前用户: {username} (ID: {user_id})")

    st.markdown(
        """
<style>
.question-card {border: 1px solid #e5e5e5; border-radius: 12px; padding: 16px; margin-bottom: 16px; background: #ffffff;}
.card-header {display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px;}
.card-title {font-weight: 600;}
.tag {background: #f2f2f2; padding: 2px 8px; border-radius: 999px; font-size: 12px;}
.status-correct {background: #e6f7e6; color: #1e7d32;}
.status-wrong {background: #fff0f0; color: #b42318;}
.status-unknown {background: #fff7e6; color: #b54708;}
.meta-line {color: #666; font-size: 12px;}
.option {border: 1px solid #eee; border-radius: 8px; padding: 8px 10px; margin: 6px 0;}
.option-correct {background: #e6f7e6; border-color: #b7eb8f;}
.option-user-wrong {background: #fff0f0; border-color: #f5b5b5;}
.option-user-correct {background: #eef7ff; border-color: #b3d4ff;}
.option-wrong-choice {color: #888; text-decoration: line-through;}
</style>
""",
        unsafe_allow_html=True,
    )
    
    # 历史记录筛选
    col1, col2 = st.columns(2)
    
    with col1:
        level = st.selectbox("选择级别", ["全部", "CET4", "CET6"])
    
    with col2:
        exam_type_filter = st.selectbox("试卷类型", ["全部", "normal_exam", "personalized_exam"])
    
    if st.button("查看历史记录"):
        # 查看历史记录逻辑
        st.success("历史记录加载成功！")
        
        # 获取试卷历史
        try:
            if level == "全部":
                exam_papers = db.get_exam_papers(user_id)
                score_rows = db.get_scores(user_id)
            else:
                exam_papers = db.get_exam_papers(user_id, level)
                score_rows = db.get_scores(user_id, level)

            score_by_exam_id = {}
            for score in score_rows:
                exam_id = score.get("exam_id")
                if exam_id is not None and exam_id not in score_by_exam_id:
                    score_by_exam_id[exam_id] = score
            
            if exam_papers:
                st.write("### 试卷历史")
                if exam_type_filter == "全部":
                    filtered_papers = list(exam_papers)
                else:
                    filtered_papers = [
                        paper for paper in exam_papers if paper.get("exam_type") == exam_type_filter
                    ]
                if not filtered_papers:
                    st.info("暂无试卷历史记录")
                    return

                for paper in filtered_papers:
                    exam_id = paper.get("exam_id")
                    paper_json = normalize_exam_paper(_parse_json_field(paper.get("paper_json")))
                    paper_info = paper_json.get("paper_info", {})
                    submission = paper_json.get("submission") if isinstance(paper_json.get("submission"), dict) else {}
                    score_row = score_by_exam_id.get(exam_id, {})
                    question_results = db.get_question_results(exam_id)
                    question_row_map = _build_question_row_map(question_results)
                    review_rows = _build_question_review_rows(paper_json, question_row_map)
                    question_map = _build_question_map(paper_json)

                    expander_label = f"{exam_id} | {paper_info.get('paper_name', '未命名试卷')}"
                    with st.expander(expander_label, expanded=False):
                        st.write(f"**试卷ID**: {exam_id}")
                        st.write(f"**试卷名**: {paper_info.get('paper_name', '未命名试卷')}")
                        st.write(f"**级别**: {paper.get('level', paper_info.get('level', 'N/A'))}")
                        st.write(f"**类型**: {paper.get('exam_type', paper_info.get('exam_type', 'N/A'))}")
                        st.write(f"**难度**: {paper_info.get('difficulty', 'N/A')}")
                        st.write(f"**题目总数**: {paper_info.get('question_count', 0)}")
                        st.write(f"**状态**: {paper.get('status', 'N/A')}")
                        st.write(f"**创建时间**: {paper.get('created_at')}")

                        st.markdown("**成绩信息**")
                        if score_row:
                            objective_score = float(score_row.get("reading_score", 0) or 0)
                            objective_possible = float(score_row.get("reading_possible", 0) or 0)
                            translation_reported = float(score_row.get("translation_score", 0) or 0)
                            writing_reported = float(score_row.get("writing_score", 0) or 0)
                            total_reported = float(score_row.get("total_score", 0) or 0)
                            total_possible_reported = float(score_row.get("total_possible", 0) or 0)
                            st.write(
                                f"总分（赋分）：{total_reported:.1f}/{total_possible_reported:.1f} | "
                                f"客观题：{objective_score:.1f}/{objective_possible:.1f} | "
                                f"翻译（赋分）：{translation_reported:.1f}/106.5 | "
                                f"写作（赋分）：{writing_reported:.1f}/106.5"
                            )
                        else:
                            st.caption("当前试卷尚未保存成绩记录")

                        if submission:
                            st.caption(
                                f"提交状态：{submission.get('status', 'unknown')} | "
                                f"提交时间：{submission.get('submitted_at', submission.get('saved_at', ''))}"
                            )

                        st.markdown("**逐题复盘**")
                        for row in review_rows:
                            question_id = row.get("question_id")
                            question_meta = question_map.get(str(question_id), {})
                            question = question_meta.get("question", {})
                            section = question_meta.get("section", {})
                            section_title = section.get("section_type", "")
                            question_type = row.get("question_type") or question.get("question_type") or section_title
                            question_text = _get_question_text(question)
                            options = _normalize_options(question)
                            user_answer = row.get("user_answer", "")
                            correct_answer = row.get("correct_answer", "")
                            is_correct = row.get("is_correct")
                            score = row.get("score", 0)
                            score_earned = row.get("score_earned", 0)

                            if is_correct is True:
                                status_label = "正确"
                                status_class = "status-correct"
                            elif is_correct is False:
                                status_label = "错误"
                                status_class = "status-wrong"
                            else:
                                status_label = "未判定"
                                status_class = "status-unknown"

                            st.markdown(
                                """
<div class="question-card">
  <div class="card-header">
    <div class="card-title">{section_title} - 题号 {question_id}</div>
    <div class="tag">{question_type}</div>
  </div>
  <div class="meta-line"><span class="tag {status_class}">{status_label}</span> 得分 {score_earned} / {score}</div>
</div>
""".format(
                                    section_title=section_title or "Section",
                                    question_id=question_id,
                                    question_type=question_type or "题目",
                                    status_class=status_class,
                                    status_label=status_label,
                                    score_earned=score_earned,
                                    score=score,
                                ),
                                unsafe_allow_html=True,
                            )

                            if question_text:
                                st.markdown(f"**题干**\n\n{question_text}")

                            is_subjective = question_type in {"translation", "writing", "essay"}
                            if is_subjective:
                                raw_score = float(score_earned or 0)
                                reported_score = _extract_reported_score(row.get("ai_feedback"), raw_score)
                                left_text = user_answer or "（未作答）"
                                right_text = correct_answer or "（暂无参考）"
                                col_user, col_ref = st.columns(2)
                                with col_user:
                                    st.markdown("**我的答案**")
                                    st.caption(f"原始分 {raw_score:.1f}/15 | 赋分 {reported_score:.1f}/106.5")
                                    st.write(left_text)
                                with col_ref:
                                    st.markdown("**参考答案**")
                                    st.write(right_text)
                            else:
                                if options:
                                    normalized_user = _normalize_answer(user_answer)
                                    normalized_correct = _normalize_answer(correct_answer)
                                    for label, text in options:
                                        normalized_label = _normalize_answer(label)
                                        is_correct_option = normalized_label == normalized_correct and normalized_correct != ""
                                        is_user_option = normalized_label == normalized_user and normalized_user != ""
                                        is_user_correct = is_user_option and is_correct_option
                                        is_user_wrong = is_user_option and not is_correct_option
                                        _render_option(label, text, is_correct_option, is_user_option, is_user_correct, is_user_wrong)

                                st.markdown(
                                    f"**标准答案**：{correct_answer or '（无）'} | **我的答案**：{user_answer or '（未作答）'}"
                                )

                            explanation = row.get("explanation") or question.get("explanation") or ""
                            if explanation:
                                st.markdown("**解析：**")
                                st.write(explanation)

                            feedback_text = _simplify_feedback(row.get("ai_feedback"))
                            if feedback_text:
                                st.markdown("**反馈：**")
                                st.write(feedback_text)
                    st.write("---")
            else:
                st.info("暂无试卷历史记录")
        except Exception as e:
            st.error(f"加载历史记录失败: {str(e)}")