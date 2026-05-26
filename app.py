"""
智能英语教学辅助系统 - 主应用入口
A负责维护此文件 - 页面框架、导航、用户认证等
"""

import streamlit as st
from utils.database import db
from modules.word_quiz import word_quiz
from modules.normal_exam import normal_exam
from modules.personalized_exam import personalized_exam
from modules.report import report
from modules.history import history

# 配置Streamlit页面
st.set_page_config(page_title="智能英语教学辅助系统", layout="wide", page_icon="📚")

# 初始化session state
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = None
if "current_page" not in st.session_state:
    st.session_state.current_page = "首页"
if "exam_generating" not in st.session_state:
    st.session_state.exam_generating = False
if "current_exam_id" not in st.session_state:
    st.session_state.current_exam_id = None

# 尝试从 URL 参数恢复登录状态
if not st.session_state.logged_in:
    params = st.query_params
    param_user_id = params.get("user_id")
    param_username = params.get("username")
    if param_user_id and param_username:
        st.session_state.logged_in = True
        st.session_state.user_id = int(param_user_id)
        st.session_state.username = param_username

st.title("📚 智能英语教学辅助系统")

pages = ["首页", "单词考察", "正常出卷", "个性化出卷", "学情报告", "历史回顾"]

if "page" not in st.session_state:
    st.session_state.page = "首页"
if "nav_page" not in st.session_state:
    param_page = st.query_params.get("page")
    if isinstance(param_page, (list, tuple)):
        param_page = param_page[0] if param_page else None
    st.session_state.nav_page = param_page if param_page in pages else "首页"

if st.session_state.exam_generating:
    st.sidebar.warning("📝 试卷生成中，切换页面可能会中断生成。")

page_options = pages
page = st.sidebar.radio(
    "导航",
    page_options,
    index=page_options.index(st.session_state.nav_page),
    key="nav_page",
    label_visibility="collapsed"
)
st.session_state.page = page
if st.query_params.get("page") != page:
    st.query_params["page"] = page

if page == "首页":
    st.subheader("四六级英语备考闭环系统")
    st.write("基于 AI 的智能学习平台，通过单词考察、错题记录、学情分析和智能出卷，帮助学生高效复习。")

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown("### 核心功能")
        st.markdown(
            "- ✅ 高频小测：优先考察错词，记录答题对错\n"
            "- ✅ 智能出卷：选择难度并控制词库配比与语法复杂度\n"
            "- ✅ AI 批改：翻译、阅读答题批改并记录错词、错语法\n"
            "- ✅ 学情报告：成绩趋势与薄弱点分析\n"
            "- ✅ 历史回顾：查看往期试卷与答案"
        )
        st.markdown("### 适用场景")
        st.write(
            "适合四六级备考学生进行个性化训练、错题强化、智能出题和学习效果监控。"
        )

    with col2:
        st.image(
            "https://cdn.pixabay.com/photo/2016/11/19/14/00/books-1835453_1280.jpg",
            caption="智能英语学习",
            width=300
        )

    st.markdown("---")
    st.markdown("### 快速上手")
    st.write("1. 在下方注册/登录账号。\n2. 进入 单词考察、正常出卷、个性化出卷、学情报告、历史回顾模块。\n3. 后续可连接 AI 出卷与批改接口，实现完整闭环。")

    # 登录表单直接在首页下方
    st.markdown("---")
    st.subheader("用户登录")

    if st.session_state.logged_in:
        st.success(f"✓ 您已登录！欢迎 {st.session_state.username}")
        if st.button("登出"):
            st.session_state.logged_in = False
            st.session_state.user_id = None
            st.session_state.username = None
            st.query_params.clear()
            st.rerun()
    else:
        tab1, tab2 = st.tabs(["登录", "注册"])

        with tab1:
            st.subheader("登录")
            username = st.text_input("用户名", key="login_username")
            password = st.text_input("密码", type="password", key="login_password")
            if st.button("登录", key="login_btn"):
                user = db.get_user(username)
                if user and user.get('password') == password:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user.get('user_id') or user.get('id')
                    st.session_state.username = user.get('username')
                    st.query_params["user_id"] = str(st.session_state.user_id)
                    st.query_params["username"] = st.session_state.username
                    st.success(f"登录成功！欢迎 {user.get('username')}")
                    st.rerun()
                else:
                    st.error("登录失败，请检查用户名和密码")

        with tab2:
            st.subheader("注册")
            new_username = st.text_input("用户名", key="reg_username")
            new_password = st.text_input("密码", type="password", key="reg_password")
            new_email = st.text_input("邮箱(可选)", key="reg_email")
            if st.button("注册", key="reg_btn"):
                try:
                    user_id = db.create_user(new_username, new_password, new_email)
                    st.success(f"注册成功！用户ID: {user_id}，请登录。")
                except Exception as e:
                    if "UNIQUE constraint failed" in str(e):
                        st.error("该用户名已存在，请选择其他用户名")
                    else:
                        st.error(f"注册失败：{str(e)}")

elif page == "单词考察":
    if not st.session_state.logged_in:
        st.warning("⚠️ 请先在首页登录")
    else:
        word_quiz(st.session_state.user_id, st.session_state.username)

elif page == "正常出卷":
    if not st.session_state.logged_in:
        st.warning("⚠️ 请先在首页登录")
    else:
        normal_exam(st.session_state.user_id, st.session_state.username)

elif page == "个性化出卷":
    if not st.session_state.logged_in:
        st.warning("⚠️ 请先在首页登录")
    elif not st.session_state.exam_generating:
        personalized_exam(st.session_state.user_id, st.session_state.username)

elif page == "学情报告":
    if not st.session_state.logged_in:
        st.warning("⚠️ 请先在首页登录")
    elif not st.session_state.exam_generating:
        report(st.session_state.user_id, st.session_state.username)

elif page == "历史回顾":
    if not st.session_state.logged_in:
        st.warning("⚠️ 请先在首页登录")
    elif not st.session_state.exam_generating:
        history(st.session_state.user_id, st.session_state.username)