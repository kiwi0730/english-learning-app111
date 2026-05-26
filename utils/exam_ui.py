"""考试页面共享 UI 工具。"""

from __future__ import annotations

import json
import re

import streamlit as st


def _extract_option_label(option: str) -> str:
    if option is None:
        return ""
    text = str(option).strip()
    match = re.match(r"^([A-Da-d])(?:[.)\s].*)?$", text)
    if match:
        return match.group(1).upper()
    return text.upper()


def _split_option_text(option: str) -> tuple[str, str]:
    if option is None:
        return "", ""
    text = str(option).strip()
    match = re.match(r"^([A-Da-d])[.)\s]+(.*)$", text)
    if match:
        return match.group(1).upper(), match.group(2).strip()
    if re.fullmatch(r"[A-Da-d]", text):
        return text.upper(), ""
    return "", text


def build_public_exam_paper(paper: dict) -> dict:
    """生成不包含标准答案的试卷副本，用于 JSON 预览。"""
    preview = json.loads(json.dumps(paper, ensure_ascii=False))
    preview.pop("answer_key", None)
    preview.pop("analysis_key", None)

    for section in preview.get("sections", []):
        if not isinstance(section, dict):
            continue
        for question in section.get("questions", []):
            if not isinstance(question, dict):
                continue
            question.pop("correct_answer", None)
            question.pop("explanation", None)

    return preview


def render_exam_sections(paper: dict, answers: dict, state_prefix: str) -> None:
    """渲染试卷题面并回填 answers。"""
    for section_index, section in enumerate(paper.get("sections", []), start=1):
        if not isinstance(section, dict):
            continue

        section_type = section.get("section_type", "")
        section_name = section.get("section_name", f"题目区块 {section_index}")
        section_content = section.get("content", "")
        section_questions = section.get("questions", [])

        st.markdown(f"#### {section_name}")
        if section.get("description"):
            st.caption(section.get("description", ""))

        if section_content and section_type in {"banked_cloze", "long_reading", "close_reading"}:
            st.markdown("**Passage:**")
            st.write(section_content)

        if section_type == "banked_cloze":
            original_options = []
            for question in section_questions:
                if not isinstance(question, dict):
                    continue
                for option in question.get("options", []):
                    if option not in original_options:
                        original_options.append(option)

            all_options = list(original_options)
            word_bank_sample = paper.get("paper_info", {}).get("word_bank_sample", [])
            if word_bank_sample and len(word_bank_sample) >= len(all_options):
                for i in range(len(all_options)):
                    word = word_bank_sample[i].get("word", "")
                    if word:
                        all_options[i] = f"{all_options[i]} {word}"

            if all_options:
                st.markdown("**Word Bank:**")
                columns = st.columns(5 if len(all_options) <= 15 else 6)
                for index, option in enumerate(all_options):
                    with columns[index % len(columns)]:
                        st.write(f"[{option}]")

            st.markdown("**Blank Items:**")
            for question in section_questions:
                if not isinstance(question, dict):
                    continue
                question_id = str(question.get("question_id"))
                stem = question.get("stem") or question.get("prompt") or "请选择单词填空"
                st.markdown(f"- **{question_id}**: {stem}")
                current_value = answers.get(question_id, "")
                display_options = [""] + all_options
                original_options_list = [""] + original_options
                current_index = 0
                if current_value:
                    for i, opt in enumerate(original_options_list):
                        if current_value == opt:
                            current_index = i
                            break
                selected = st.selectbox(
                    f"{question_id} 选择答案",
                    options=display_options,
                    index=current_index,
                    key=f"{state_prefix}_select_{question_id}",
                    label_visibility="collapsed",
                )
                if selected:
                    first_char = selected.split()[0] if selected.strip() else ""
                    if first_char and first_char in original_options:
                        answers[question_id] = first_char
                    else:
                        answers[question_id] = selected
                else:
                    answers[question_id] = ""

        elif section_type == "long_reading":
            st.markdown("**Statements:**")
            for question in section_questions:
                if not isinstance(question, dict):
                    continue
                question_id = str(question.get("question_id"))
                stem = question.get("stem") or question.get("prompt") or "请选择匹配的段落"
                st.markdown(f"**{question_id}** {stem}")

                options = question.get("options") or []
                if options:
                    current_value = answers.get(question_id, "")
                    option_values = [""] + [str(option) for option in options]
                    index = option_values.index(str(current_value)) if str(current_value) in option_values else 0
                    answers[question_id] = st.radio(
                        f"{question_id} 选择答案",
                        options=option_values,
                        index=index,
                        key=f"{state_prefix}_radio_{question_id}",
                        horizontal=True,
                        label_visibility="collapsed",
                    )

        elif section_type == "close_reading":
            for question in section_questions:
                if not isinstance(question, dict):
                    continue
                question_id = str(question.get("question_id"))
                stem = question.get("stem") or question.get("prompt") or "请作答"

                st.markdown(f"**{question_id}** {stem}")
                options = question.get("options") or []
                if options:
                    option_items = []
                    for option in options:
                        label, option_text = _split_option_text(option)
                        if label:
                            display_text = f"{label} {option_text}".strip()
                            option_items.append((display_text, label))
                        else:
                            option_items.append((option_text, option_text))

                    display_options = [display for display, _ in option_items]
                    value_map = {display: value for display, value in option_items}

                    current_value = answers.get(question_id, "")
                    current_display = ""
                    if current_value:
                        for display, value in option_items:
                            if current_value == value or current_value == display:
                                current_display = display
                                break
                        if not current_display:
                            normalized_current = _extract_option_label(current_value)
                            for display, value in option_items:
                                if normalized_current and value == normalized_current:
                                    current_display = display
                                    break

                    option_values = [""] + display_options
                    index = option_values.index(current_display) if current_display in option_values else 0
                    selected_display = st.radio(
                        f"{question_id} 选择答案",
                        options=option_values,
                        index=index,
                        key=f"{state_prefix}_radio_{question_id}",
                        horizontal=False,
                        label_visibility="collapsed",
                    )
                    answers[question_id] = value_map.get(selected_display, "") if selected_display else ""
                else:
                    answers[question_id] = st.text_input(
                        question.get("prompt", "请输入答案"),
                        value=answers.get(question_id, ""),
                        key=f"{state_prefix}_input_{question_id}",
                    )

        elif section_type == "writing":
            for question in section_questions:
                if not isinstance(question, dict):
                    continue
                question_id = str(question.get("question_id"))
                stem = question.get("stem") or "请写作文"
                prompt = question.get("prompt", "")  # 具体的作文题目
                
                st.markdown(f"**{question_id}. {stem}**")
                
                # 显示具体的作文题目
                if prompt:
                    st.markdown(f"**题目：** {prompt}")
                
                passage = question.get("passage", "")
                if passage:
                    st.info(passage)
        
                answers[question_id] = st.text_area(
                    "请在此输入作文（注意字数要求）",
                    value=answers.get(question_id, ""),
                    key=f"{state_prefix}_textarea_{question_id}",
                    height=200,
                )
        elif section_type == "translation":
            for question in section_questions:
                if not isinstance(question, dict):
                    continue
                question_id = str(question.get("question_id"))
                passage = question.get("passage") or question.get("stem") or "请翻译"

                st.markdown(f"**{question_id}. 翻译以下段落：**")
                st.info(passage)

                answers[question_id] = st.text_area(
                    "请在此输入英文翻译",
                    value=answers.get(question_id, ""),
                    key=f"{state_prefix}_textarea_{question_id}",
                    height=150,
                )

        else:
            if section_content:
                st.write(section_content)
            for question in section_questions:
                if not isinstance(question, dict):
                    continue
                question_id = str(question.get("question_id"))
                question_type = question.get("question_type", "")
                st.markdown(f"**{question_id}. {question.get('stem') or question.get('prompt') or '请作答'}**")
                if question.get("passage"):
                    st.write(question["passage"])

                options = question.get("options") or []
                if options:
                    current_value = answers.get(question_id, "")
                    option_values = [""] + [str(option) for option in options]
                    index = option_values.index(str(current_value)) if str(current_value) in option_values else 0
                    answers[question_id] = st.radio(
                        f"{question_id} 选择答案",
                        options=option_values,
                        index=index,
                        key=f"{state_prefix}_radio_{question_id}",
                        horizontal=True,
                        label_visibility="collapsed",
                    )
                elif question_type in {"writing", "translation"}:
                    answers[question_id] = st.text_area(
                        question.get("prompt", "请输入答案"),
                        value=answers.get(question_id, ""),
                        key=f"{state_prefix}_textarea_{question_id}",
                        height=180,
                    )
                else:
                    answers[question_id] = st.text_input(
                        question.get("prompt", "请输入答案"),
                        value=answers.get(question_id, ""),
                        key=f"{state_prefix}_input_{question_id}",
                    )