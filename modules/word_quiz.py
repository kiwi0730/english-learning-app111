"""
单词考察页面
C 负责维护此文件
纯业务逻辑：AI调用、提交批改
"""

import random

import streamlit as st

from modules.word_quiz_ui import (
    init_word_quiz_state,
    parse_word_quiz_response,
    render_word_quiz_page_header,
    handle_word_quiz,
)
from utils.call_ai import call_ai_full
from utils.database import db

PREFIX = "word_quiz"


def _build_confusing_options_prompt(words: list) -> str:
    """生成易混淆选项的 prompt"""
    word_list = "\n".join([f"- {w.get('word', '')}: {w.get('meaning', '')}" for w in words])
    return f"""
你是一个英语单词辅助出题助手。请为以下每个单词生成2个易混淆的中文选项。

要求：
1. 每个单词生成2个错误选项（中文含义必须与正确答案词性相同）
2. 例如：正确答案是"苹果"（名词），错误选项可以是"梨子"、"香蕉"
3. 保持输出为合法的JSON格式

输入单词：
{word_list}

输出格式：
{{
    "words": [
        {{
            "word": "apple",
            "correct_meaning": "苹果",
            "confusing_options": ["梨子", "香蕉"]
        }},
        ...
    ]
}}
""".strip()


def _generate_quiz(user_id: int, level: str, difficulty: int, word_count: int) -> None:
    """生成单词小测"""
    try:
        target_wrong = int(word_count * 0.2)
        wrong_rows = db.get_wrong_words(user_id, level)
        random.shuffle(wrong_rows)
        wrong_words = []

        for row in wrong_rows:
            if len(wrong_words) >= target_wrong:
                break
            word = row.get("word")
            if not word:
                continue
            word_info = db.search_word(word, level)
            if not word_info:
                continue
            wrong_words.append(word_info)

        remaining_count = word_count - len(wrong_words)
        remaining_words = []
        attempts = 0
        while len(remaining_words) < remaining_count and attempts < 5:
            remaining = remaining_count - len(remaining_words)
            fetch_count = min(max(remaining * 2, remaining + 4), remaining_count + 20)
            candidates = db.get_words_by_difficulty(level, difficulty, fetch_count)
            for item in candidates:
                word = item.get("word")
                if not word:
                    continue
                remaining_words.append(item)
                if len(remaining_words) >= remaining_count:
                    break
            attempts += 1

        words = wrong_words + remaining_words

        random.shuffle(words)
        
        prompt = _build_confusing_options_prompt(words)
        result = call_ai_full(prompt, max_retries=2, max_tokens=2048, timeout=180)
        
        if not result or result.get("status") != "success":
            st.session_state[f"{PREFIX}_status"] = "failed"
            st.session_state[f"{PREFIX}_error"] = "AI生成失败"
            return
        
        content = result.get("content", "")
        quiz_questions = parse_word_quiz_response(content, words)
        
        if not quiz_questions:
            st.session_state[f"{PREFIX}_status"] = "failed"
            st.session_state[f"{PREFIX}_error"] = "解析题目失败"
            return
        
        st.session_state[f"{PREFIX}_data"] = quiz_questions
        st.session_state[f"{PREFIX}_answers"] = {}
        st.session_state[f"{PREFIX}_status"] = "ready"
    except Exception as e:
        st.session_state[f"{PREFIX}_status"] = "failed"
        st.session_state[f"{PREFIX}_error"] = str(e)


def _generate_review_quiz(user_id: int, level: str, word_count: int) -> None:
    """生成复习题目（基于用户历史答题记录）"""
    try:
        # 获取用户已考察过的单词
        tested_words = db.get_tested_words(user_id, level)
        
        # 如果没有历史记录，按普通考察生成
        if not tested_words:
            _generate_quiz(user_id, level, 5, word_count)
            return
        
        # 获取已考察单词的唯一列表（去重）
        tested_word_set = {item.get("word") for item in tested_words}
        tested_word_list = list(tested_word_set)
        
        # 如果历史单词数量少于要求数量，补充新单词
        if len(tested_word_list) < word_count:
            # 先从历史单词中随机选取
            random.shuffle(tested_word_list)
            selected_words = tested_word_list[:min(len(tested_word_list), word_count)]
            
            # 计算还需要多少新单词
            remaining_count = word_count - len(selected_words)
            
            # 获取新单词（排除已考察过的）
            remaining_words = []
            attempts = 0
            while len(remaining_words) < remaining_count and attempts < 5:
                candidates = db.get_words_by_difficulty(level, 5, remaining_count * 2)
                for item in candidates:
                    word = item.get("word")
                    if word and word not in tested_word_set:
                        remaining_words.append(item)
                        if len(remaining_words) >= remaining_count:
                            break
                attempts += 1
            
            words = selected_words + remaining_words
        else:
            # 如果历史单词足够，直接从中选取
            random.shuffle(tested_word_list)
            words = tested_word_list[:word_count]
        
        # 将单词字符串转换为完整的单词信息
        word_info_list = []
        for word in words:
            if isinstance(word, str):
                word_info = db.search_word(word, level)
                if word_info:
                    word_info_list.append(word_info)
            else:
                word_info_list.append(word)
        
        # 生成易混淆选项
        prompt = _build_confusing_options_prompt(word_info_list)
        result = call_ai_full(prompt, max_retries=2, max_tokens=2048, timeout=180)
        
        if not result or result.get("status") != "success":
            st.session_state[f"{PREFIX}_status"] = "failed"
            st.session_state[f"{PREFIX}_error"] = "AI生成失败"
            return
        
        content = result.get("content", "")
        quiz_questions = parse_word_quiz_response(content, word_info_list)
        
        if not quiz_questions:
            st.session_state[f"{PREFIX}_status"] = "failed"
            st.session_state[f"{PREFIX}_error"] = "解析题目失败"
            return
        
        st.session_state[f"{PREFIX}_data"] = quiz_questions
        st.session_state[f"{PREFIX}_answers"] = {}
        st.session_state[f"{PREFIX}_status"] = "ready"
    except Exception as e:
        st.session_state[f"{PREFIX}_status"] = "failed"
        st.session_state[f"{PREFIX}_error"] = str(e)


def _do_submit_quiz(user_id: int) -> None:
    """提交答案并批改"""
    quiz_data = st.session_state.get(f"{PREFIX}_data", [])
    answers = st.session_state.get(f"{PREFIX}_answers", {})
    level = st.session_state.get(f"{PREFIX}_level", "CET4")
    
    correct_count = 0
    total_count = len(quiz_data)
    results = []
    
    for q in quiz_data:
        word = q.get("word", "")
        correct_answer = q.get("correct_answer", "")
        user_answer = answers.get(word, "")
        
       
        is_correct = correct_answer in user_answer if user_answer else False
        
        if is_correct:
            correct_count += 1
        
        results.append({
            "word": word,
            "correct_answer": q.get("correct_meaning", ""),
            "user_answer": user_answer,
            "is_correct": is_correct,
        })
        
        try:
            db.save_word_result(
                user_id=user_id,
                level=level,
                word=word,
                is_correct=is_correct,
                source="quiz"
            )
        except Exception:
            pass
    
    st.session_state[f"{PREFIX}_result"] = {
        "correct_count": correct_count,
        "total_count": total_count,
        "accuracy": correct_count / total_count * 100 if total_count > 0 else 0,
        "details": results,
    }
    st.session_state[f"{PREFIX}_status"] = "submitted"


def word_quiz(user_id, username):
    """单词考察页面"""
    init_word_quiz_state()

    # 获取当前模式（quiz/review）
    mode = st.session_state.get(f"{PREFIX}_mode", "quiz")
    
    # 根据模式渲染不同标题
    render_word_quiz_page_header(user_id, username, mode)
    
    handle_word_quiz(
        user_id=user_id,
        on_generate=lambda l, d, w: _generate_quiz(user_id, l, d, w),
        on_submit=lambda uid: _do_submit_quiz(uid),
        on_review=lambda uid, l, w: _generate_review_quiz(uid, l, w)
    )