"""
学情报告页面
D 负责维护此文件
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from utils.database import db


def report(user_id, username):
    """学情报告页面"""
    st.subheader("📈 学情报告")
    st.write(f"当前用户: {username} (ID: {user_id})")
    
    # 报告筛选
    col1, col2 = st.columns(2)
    
    with col1:
        level = st.selectbox("选择级别", ["CET4", "CET6"])
    
    with col2:
        time_range = st.selectbox("时间范围", ["最近一周", "最近一月", "最近三月"])
    
    if st.button("生成学情报告"):
        # 生成学情报告逻辑
        st.success("学情报告生成成功！")
        
        # 获取成绩记录
        try:
            scores = db.get_scores(user_id, level=level, time_range=time_range)
            
            if scores:
                st.write("### 成绩趋势")
                scores = sorted(scores, key=lambda x: x["date"])
                df = pd.DataFrame(scores)
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")

                st.line_chart(df["total_score"])

                # 计算每张试卷五大题型的平均得分，用于雷达图
                radar_labels = [
                    "完形/段落填空",
                    "长篇阅读",
                    "仔细阅读",
                    "翻译",
                    "写作",
                ]
                radar_keys = [
                    "banked_cloze",
                    "long_reading",
                    "close_reading",
                    "translation",
                    "writing",
                ]
                section_scores = {key: [] for key in radar_keys}

                exam_ids = [score["exam_id"] for score in scores if score.get("exam_id") is not None]
                for exam_id in exam_ids:
                    question_results = db.get_question_results(exam_id)
                    per_exam = {key: 0.0 for key in radar_keys}
                    found_section = {key: False for key in radar_keys}
                    for q in question_results:
                        qtype = q.get("question_type")
                        if qtype in radar_keys:
                            per_exam[qtype] += float(q.get("score_earned") or 0)
                            found_section[qtype] = True
                    for key in radar_keys:
                        if found_section[key]:
                            section_scores[key].append(per_exam[key])

                radar_values = []
                for key in radar_keys:
                    values = section_scores[key]
                    avg = float(sum(values) / len(values)) if values else 0.0
                    radar_values.append(avg)

                radar_df = pd.DataFrame({"题型": radar_labels, "平均得分": radar_values})
                fig = px.line_polar(
                    radar_df,
                    r="平均得分",
                    theta="题型",
                    line_close=True,
                    title="五大题型平均得分雷达图",
                    markers=True,
                )
                fig.update_traces(
                    fill="toself",
                    hovertemplate="%{theta}: %{r:.1f}<extra></extra>",
                    marker=dict(size=8),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("暂无成绩记录")
                
        except Exception as e:
            st.error(f"生成学情报告失败: {str(e)}")