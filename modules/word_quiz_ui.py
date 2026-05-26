"""
单词小测 UI 渲染模块
"""

import json
import random
import time

import streamlit as st

try:
    from json_repair import repair_json
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False
    repair_json = None

PREFIX = "word_quiz"


def init_word_quiz_state():
    """初始化单词小测状态"""
    keys = {
        f"{PREFIX}_data": None,
        f"{PREFIX}_answers": {},
        f"{PREFIX}_status": "idle",
        f"{PREFIX}_result": None,
        f"{PREFIX}_level": "CET4",
        f"{PREFIX}_difficulty": 5,
        f"{PREFIX}_word_count": 20,
        f"{PREFIX}_error": None,
        f"{PREFIX}_mode": "quiz",  # quiz: 正常考察, review: 复习模式
    }
    for key, default in keys.items():
        if key not in st.session_state:
            st.session_state[key] = default


def render_word_quiz_page_header(user_id: int, username: str, mode: str = "quiz") -> None:
    """渲染页面标题与用户信息"""
    if mode == "review":
        st.subheader("🔄 单词复习")
        st.write(f"当前用户: {username} (ID: {user_id}) - 复习模式")
    else:
        st.subheader("📚 单词考察")
        st.write(f"当前用户: {username} (ID: {user_id})")


def _extract_json_payload(content: str):
    """从 AI 输出中提取 JSON 对象"""
    if not content:
        return None
    
    text = str(content).strip()
    
    fenced_match = text.find("```json")
    if fenced_match != -1:
        end = text.find("```", fenced_match + 7)
        if end != -1:
            text = text[fenced_match + 7:end]
    
    start = text.find("{")
    end = text.rfind("}")
    
    if start == -1 or end == -1 or end <= start:
        return None
    
    candidate = text[start:end + 1]
    
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    
    if HAS_JSON_REPAIR and repair_json:
        try:
            repaired = repair_json(candidate)
            if repaired:
                return json.loads(repaired) if isinstance(repaired, str) else repaired
        except Exception:
            pass
    
    return None


def parse_word_quiz_response(content: str, words: list) -> list:
    """解析AI返回的易混淆选项，构造4选1题目"""
    try:
        payload = _extract_json_payload(content)
        if not payload:
            return []
        
        ai_words = payload.get("words", [])
        if not ai_words:
            return []
        
        word_map = {w.get("word"): w for w in words}
        
        quiz_questions = []
        for ai_word in ai_words:
            word = ai_word.get("word", "")
            original_word = word_map.get(word)
            if not original_word:
                continue
            
            correct_meaning = ai_word.get("correct_meaning", original_word.get("meaning", ""))
            confusing = ai_word.get("confusing_options", [])
            
            if len(confusing) < 2:
                continue
            
            options = [correct_meaning] + confusing[:2]
            random.shuffle(options)
            
            quiz_questions.append({
                "word": word,
                "correct_meaning": correct_meaning,
                "correct_answer": correct_meaning,
                "options": options,
            })
        
        return quiz_questions
    except Exception:
        return []


def render_word_quiz_setup(prefix: str = PREFIX) -> tuple:
    """渲染设置面板"""
    col1, col2 = st.columns(2)
    
    with col1:
        level = st.selectbox(
            "选择级别", 
            ["CET4", "CET6"], 
            index=0 if st.session_state.get(f"{prefix}_level") == "CET4" else 1
        )
        st.caption("考察类型：英译中选择题")
    
    with col2:
        word_count = st.slider("单词数量", 5, 50, 20)
        difficulty = st.slider("难度等级", 1, 10, 5)
    
    return level, difficulty, word_count


def render_word_quiz_interface(quiz_data: list, answers: dict, prefix: str = PREFIX) -> None:
    """渲染答题界面"""
    st.markdown("### 📝 单词考察")
    
    for idx, q in enumerate(quiz_data, 1):
        word = q.get("word", "")
        options = q.get("options", [])
        
        st.markdown(f"**{idx}. {word}**")
        
        options_with_label = ["请选择"] + [f"{chr(65+i)}. {opt}" for i, opt in enumerate(options)]
        current_value = answers.get(word, "")
        
        if current_value:
            current_index = options_with_label.index(current_value) if current_value in options_with_label else 0
        else:
            current_index = 0
        
        answers[word] = st.radio(
            f"选择 {idx} 的中文含义",
            options=options_with_label,
            index=current_index,
            key=f"{prefix}_radio_{idx}",
            label_visibility="collapsed"
        )
    
    st.session_state[f"{prefix}_answers"] = answers


def render_word_quiz_result(result: dict) -> None:
    """渲染结果界面"""
    st.markdown("### 📊 考察结果")
    st.write(f"**正确率**: {result.get('correct_count', 0)}/{result.get('total_count', 0)} = {result.get('accuracy', 0):.1f}%")
    
    st.markdown("#### 详细结果")
    details = result.get("details", [])
    for item in details:
        status = "✅" if item.get("is_correct") else "❌"
        st.write(f"{status} **{item.get('word', '')}** - 正确: {item.get('correct_answer', '')}")


def handle_word_quiz(
    user_id: int,
    on_generate: callable,
    on_submit: callable,
    on_review: callable = None,
    prefix: str = PREFIX
):
    """统一处理单词小测页面（状态机）- 同步调用版本"""
    status = st.session_state.get(f"{prefix}_status", "idle")
    
    if status == "idle":
        level, difficulty, word_count = render_word_quiz_setup(prefix)
        
        st.session_state[f"{prefix}_level"] = level
        st.session_state[f"{prefix}_difficulty"] = difficulty
        st.session_state[f"{prefix}_word_count"] = word_count
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("开始考察", type="primary"):
                st.session_state[f"{prefix}_mode"] = "quiz"
                with st.spinner("AI 正在生成易混淆选项，请稍候..."):
                    on_generate(level, difficulty, word_count)
                
                new_status = st.session_state.get(f"{prefix}_status", "idle")
                if new_status == "ready":
                    st.rerun()
                elif new_status == "failed":
                    st.error(st.session_state.get(f"{prefix}_error", "生成失败"))
        
        with col2:
            if st.button("复习", type="secondary"):
                st.session_state[f"{prefix}_mode"] = "review"
                with st.spinner("正在加载复习题目..."):
                    on_review(user_id, level, word_count)
                
                new_status = st.session_state.get(f"{prefix}_status", "idle")
                if new_status == "ready":
                    st.rerun()
                elif new_status == "failed":
                    st.error(st.session_state.get(f"{prefix}_error", "加载失败"))
    
    elif status == "ready":
        render_word_quiz_interface(
            quiz_data=st.session_state.get(f"{prefix}_data", []),
            answers=st.session_state.get(f"{prefix}_answers", {}),
            prefix=prefix
        )
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("提交答案", type="primary"):
                on_submit(user_id)
        with col2:
            if st.button("重新开始"):
                st.session_state[f"{prefix}_status"] = "idle"
                st.session_state[f"{prefix}_data"] = None
                st.session_state[f"{prefix}_answers"] = {}
                st.session_state[f"{prefix}_result"] = None
                st.rerun()
    
    elif status == "submitted":
        render_word_quiz_result(st.session_state.get(f"{prefix}_result", {}))
        
        if st.button("再来一次"):
            st.session_state[f"{prefix}_status"] = "idle"
            st.session_state[f"{prefix}_data"] = None
            st.session_state[f"{prefix}_answers"] = {}
            st.session_state[f"{prefix}_result"] = None
            st.rerun()
    
    elif status == "failed":
        error = st.session_state.get(f"{prefix}_error", "未知错误")
        st.error(f"生成失败: {error}")
        if st.button("返回重试"):
            st.session_state[f"{prefix}_status"] = "idle"
            st.rerun()