"""出卷页面通用逻辑。"""

from __future__ import annotations

import json
import time

import streamlit as st

from utils.database import db
from utils.exam_schema import build_answers_payload, normalize_exam_paper
from utils.exam_ui import build_public_exam_paper, render_exam_sections

_GENERATING_PARAM = "generating"
_GENERATING_PREFIX = "exam_"
_PREFIX_EXAM_TYPE_MAP = {
    "normal_exam_v2": "normal_exam",
    "personalized_exam_v2": "personalized_exam",
}


def _extract_error_text(record: dict | None, fallback: str = "生成失败") -> str:
    if not record:
        return fallback
    raw_paper = record.get("paper_json") or {}
    if isinstance(raw_paper, str):
        try:
            raw_paper = json.loads(raw_paper)
        except json.JSONDecodeError:
            raw_paper = {}
    if isinstance(raw_paper, dict):
        return raw_paper.get("paper_info", {}).get("answers_error", fallback)
    return fallback


def _apply_ready_record(prefix: str, record: dict) -> None:
    paper, answers = _load_paper_from_record(record)
    st.session_state[f"{prefix}_paper"] = paper
    st.session_state[f"{prefix}_answers"] = answers
    st.session_state[f"{prefix}_processing"] = False
    st.session_state[f"{prefix}_status"] = "生成成功，已从数据库加载"


def _load_paper_from_record(record: dict) -> tuple[dict, dict]:
    raw_paper = record.get("paper_json") or {}
    if isinstance(raw_paper, str):
        try:
            raw_paper = json.loads(raw_paper)
        except json.JSONDecodeError:
            raw_paper = {}
    paper = normalize_exam_paper(raw_paper)
    submission = paper.get("submission") if isinstance(paper.get("submission"), dict) else {}
    answers = submission.get("answers") if isinstance(submission.get("answers"), dict) else {}
    return paper, dict(answers)


def set_generating_query_param(exam_id: int) -> None:
    if not exam_id:
        return
    st.query_params[_GENERATING_PARAM] = f"{_GENERATING_PREFIX}{exam_id}"


def clear_generating_query_param() -> None:
    generating_value = st.query_params.get(_GENERATING_PARAM)
    if not generating_value:
        return
    st.query_params.pop(_GENERATING_PARAM, None)


def resume_from_query_param(prefix: str, user_id: int) -> bool:
    generating_value = st.query_params.get(_GENERATING_PARAM)
    if not generating_value:
        return False

    if st.session_state.get(f"{prefix}_processing"):
        return False

    text = str(generating_value)
    if not text.startswith(_GENERATING_PREFIX):
        return False

    exam_id_text = text[len(_GENERATING_PREFIX):]
    try:
        exam_id = int(exam_id_text)
    except ValueError:
        return False

    record = db.get_exam_paper(exam_id)
    if not record:
        clear_generating_query_param()
        return False

    expected_exam_type = _PREFIX_EXAM_TYPE_MAP.get(prefix)
    if expected_exam_type and record.get("exam_type") != expected_exam_type:
        return False

    if record.get("user_id") != user_id:
        return False

    status = record.get("status")
    if status == "ready":
        _apply_ready_record(prefix, record)
        clear_generating_query_param()
        return True

    if status == "failed":
        error_text = _extract_error_text(record)
        st.session_state[f"{prefix}_processing"] = False
        st.session_state[f"{prefix}_status"] = f"生成失败：{error_text}"
        clear_generating_query_param()
        return True

    if status in {"processing", "pending"}:
        st.session_state[f"{prefix}_exam_id"] = exam_id
        st.session_state[f"{prefix}_processing"] = True
        st.session_state[f"{prefix}_status"] = f"生成中，exam_id = {exam_id}"
        return True

    return False


def init_exam_state(prefix: str) -> None:
    keys = {
        f"{prefix}_paper": None,
        f"{prefix}_exam_id": None,                                                                   
        f"{prefix}_answers": {},
        f"{prefix}_status": "未生成",
        f"{prefix}_result": None,
        f"{prefix}_processing": False,
    }
    for key, default in keys.items():
        if key not in st.session_state:
            st.session_state[key] = default

    if "exam_generating" not in st.session_state:
        st.session_state.exam_generating = False




def render_normal_exam_header(user_id: int, username: str, ai_available: bool) -> None:
    st.title("正常出卷")
    st.write(f"当前用户: {username} (ID: {user_id})")
    if ai_available:
        st.caption("AI 出题接口已连接")
    else:
        st.warning("AI 出题接口不可用，将使用本地题库兜底")
    st.caption("先选择 CET4 / CET6，再按难度从数据库抽取 50 个词，生成对应试卷 JSON，答案与解析将后台生成。")


def render_normal_exam_setup(prefix: str) -> tuple[str, int]:
    level = st.selectbox("选择级别", ["CET4", "CET6"], key=f"{prefix}_level")
    difficulty = st.select_slider(
        "难度等级",
        options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        value=5,
        key=f"{prefix}_difficulty",
    )
    st.number_input(
        "词库抽样数量",
        min_value=50,
        max_value=50,
        value=50,
        step=1,
        disabled=True,
        key=f"{prefix}_word_count",
        help="固定抽取 50 个单词作为出题参考。",
    )
    return level, difficulty


def render_personalized_exam_header(user_id: int, username: str) -> None:
    st.title("个性化出卷")
    st.write(f"当前用户: {username} (ID: {user_id})")
    st.caption("根据近 N 次正确率推荐难度，并结合错词库生成与正常出卷同格式的个性化试卷。")


def render_personalized_exam_setup(prefix: str) -> tuple[str, int, int]:
    col1, col2, col3 = st.columns(3)
    with col1:
        level = st.selectbox("选择级别", ["CET4", "CET6"], key=f"{prefix}_level")
    with col2:
        recent_n = st.selectbox("近 N 次成绩", list(range(1, 11)), index=2, key=f"{prefix}_recent_n")
    with col3:
        wrong_word_count = st.selectbox(
            "结合错词数量",
            list(range(10, 51, 5)),
            index=0,
            key=f"{prefix}_wrong_word_count",
        )
    return level, recent_n, wrong_word_count


def render_personalized_recommendation(
    recent_scores: list,
    recent_n: int,
    recommended_difficulty: float,
) -> None:
    if recent_scores:
        st.info(f"近 {recent_n} 次历史成绩已读取，推荐难度：{recommended_difficulty:.1f}")
    else:
        st.warning("暂无历史成绩，默认使用难度 0.7 生成。")

    st.caption("个性化试卷与正常出卷使用同一套试卷结构、答案格式和解析格式，差异仅在推荐难度与错词融合。")


def render_generate_resume_controls(prefix: str, generate_label: str) -> tuple[bool, bool]:
    col_generate, col_resume = st.columns(2)
    is_processing = st.session_state.get(f"{prefix}_processing", False)
    with col_generate:
        generate_clicked = st.button(
            generate_label,
            use_container_width=True,
            disabled=is_processing,
            type="primary",
        )
    with col_resume:
        resume_clicked = st.button("继续最近草稿", width="stretch", disabled=is_processing)
        if is_processing:
            st.caption("试卷生成中，请稍候完成后再继续草稿。")
    return generate_clicked, resume_clicked


def render_exam_status(prefix: str) -> None:
    st.info(f"当前状态：{st.session_state.get(f'{prefix}_status')}")


def render_exam_empty_notice() -> None:
    st.info("先点击生成试卷，再进入答题页面。")


def report_generation_error(prefix: str, status_message: str, ui_message: str | None = None) -> None:
    st.session_state[f"{prefix}_status"] = status_message
    st.error(ui_message or status_message)


def resume_latest_ready(user_id: int, exam_type: str, prefix: str) -> bool:
    latest = db.get_latest_exam_paper(
        user_id,
        exam_type=exam_type,
        status=["ready"],
    )
    if not latest:
        st.info("暂无可恢复的草稿")
        return False

    paper, answers = _load_paper_from_record(latest)
    st.session_state[f"{prefix}_paper"] = paper
    st.session_state[f"{prefix}_exam_id"] = latest.get("exam_id")
    st.session_state[f"{prefix}_answers"] = answers
    st.session_state[f"{prefix}_result"] = None
    st.session_state[f"{prefix}_processing"] = False
    st.session_state[f"{prefix}_status"] = f"已恢复草稿，exam_id = {latest.get('exam_id')}"
    st.success("草稿已恢复")
    return True


def poll_exam_status(prefix: str, exam_id: int) -> None:
    latest = db.get_exam_paper(exam_id)
    status = latest.get("status") if latest else None
    if status == "ready":
        _apply_ready_record(prefix, latest)
        clear_generating_query_param()
        st.rerun()
    elif status == "failed":
        error_text = _extract_error_text(latest)
        st.session_state[f"{prefix}_processing"] = False
        st.session_state[f"{prefix}_status"] = f"生成失败：{error_text}"
        clear_generating_query_param()
    else:
        with st.spinner("试卷生成中..."):
            time.sleep(2)
            st.rerun()


def render_exam_header(paper: dict, level: str, difficulty: int | float | str) -> None:
    paper_info = paper.get("paper_info", {})
    level_value = paper_info.get("level", level)
    difficulty_value = paper_info.get("difficulty", difficulty)
    question_count = paper_info.get("question_count", len(_flatten_questions(paper)))
    st.write(
        f"试卷名：{paper_info.get('paper_name', '未命名试卷')} | 级别：{level_value} | 难度：{difficulty_value} | 题目数：{question_count}"
    )
    st.caption(f"出题方式：{paper_info.get('generation_mode', 'unknown')} | 生成时间：{paper_info.get('generated_at', '')}")


def render_exam_body(paper: dict, prefix: str) -> None:
    preview_tabs = st.tabs(["答题页面", "JSON 预览"])
    with preview_tabs[0]:
        answers = dict(st.session_state.get(f"{prefix}_answers", {}))
        render_exam_sections(paper, answers, prefix)
        st.session_state[f"{prefix}_answers"] = answers

    with preview_tabs[1]:
        st.json(build_public_exam_paper(paper))


def render_save_submit_controls(prefix: str, paper: dict, user_id: int, grade_callback=None) -> None:
    save_col, submit_col = st.columns(2)
    with save_col:
        if st.button("保存草稿", width="stretch"):
            try:
                exam_id = st.session_state.get(f"{prefix}_exam_id")
                if exam_id is None:
                    raise RuntimeError("请先生成试卷")
                answers = st.session_state.get(f"{prefix}_answers", {})
                save_payload = build_answers_payload("draft", answers)
                paper_copy = dict(paper)
                paper_copy["submission"] = save_payload
                db.update_exam_paper(exam_id, paper_json=paper_copy)
                st.success("已保存当前答题草稿，并覆盖数据库中的旧草稿")
            except Exception as exc:
                st.error(f"保存失败：{exc}")

    with submit_col:
        if st.button("提交批改", width="stretch"):
            try:
                exam_id = st.session_state.get(f"{prefix}_exam_id")
                if exam_id is None:
                    raise RuntimeError("请先生成试卷")
                answers = st.session_state.get(f"{prefix}_answers", {})
                submit_payload = build_answers_payload("graded", answers)
                paper_copy = dict(paper)
                paper_copy["submission"] = submit_payload
                db.update_exam_paper(exam_id, paper_json=paper_copy)
                if grade_callback is None:
                    raise RuntimeError("未提供批改函数")
                grading_summary = grade_callback(exam_id, paper_copy, answers, user_id=user_id)
                st.session_state[f"{prefix}_result"] = grading_summary
                # 根据批改结果动态显示得分信息
                objective_score = grading_summary.get('objective_score', 0)
                objective_total = grading_summary.get('objective_total', 0)
                writing_score = grading_summary.get('writing_score', 0)
                translation_score = grading_summary.get('translation_score', 0)
                
                if writing_score > 0 or translation_score > 0:
                    # 如果有主观题得分，则显示完整的得分信息
                    total_reported = grading_summary.get('total_reported', 0)
                    st.success(
                        f"提交成功，客观题得分 {objective_score}/{objective_total}，写作得分 {writing_score}，翻译得分 {translation_score}"
                    )
                else:
                    # 如果没有主观题得分，则显示原始消息
                    st.success(
                        f"提交成功，客观题得分 {objective_score}/{objective_total}，主观题已置 0"
                    )
            except Exception as exc:
                st.error(f"提交失败：{exc}")

    result = st.session_state.get(f"{prefix}_result")
    if result:
        st.markdown("### 提交结果")
        st.json(result)

    exam_id = st.session_state.get(f"{prefix}_exam_id")
    if exam_id is not None:
        st.success(f"最近一次保存/提交的试卷ID：{exam_id}")


def render_exit_controls(prefix: str) -> None:
    exam_id = st.session_state.get(f"{prefix}_exam_id")
    if exam_id and not st.session_state.get("exam_generating", False):
        st.caption("退出答题不会保存草稿，请先点击保存草稿。")
        if st.button("退出答题", type="secondary"):
            st.session_state[f"{prefix}_paper"] = None
            st.session_state[f"{prefix}_exam_id"] = None
            st.session_state[f"{prefix}_answers"] = {}
            st.session_state[f"{prefix}_result"] = None
            st.session_state[f"{prefix}_status"] = "已清空"
            st.session_state[f"{prefix}_processing"] = False
            st.session_state.exam_generating = False
            st.success("试卷已完成，可以切换页面了！")
            st.rerun()


def _flatten_questions(paper):
    questions = []
    for section in paper.get("sections", []):
        if not isinstance(section, dict):
            continue
        for item in section.get("questions", []):
            if isinstance(item, dict):
                questions.append(item)
    return questions