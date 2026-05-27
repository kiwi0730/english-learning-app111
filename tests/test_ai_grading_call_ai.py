"""AI批改测试脚本（模拟数据）

运行方式：
  python tests/test_ai_grading_call_ai.py
"""

from pathlib import Path
import sys

# Allow running as a standalone script from repo root.
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.call_ai import call_ai_full, check_ai


def build_mock_prompt() -> str:
    """构造一个用于AI批改的模拟提示词"""
    question = {
        "type": "writing",
        "content": "Write a short paragraph about your favorite hobby.",
        "reference_answer": "My favorite hobby is reading because it helps me relax and learn new ideas.",
        "score": 15
    }
    user_answer = "My favorite hobby is read books. It makes me relax and learn new ideas."

    prompt = f"""
你是英语考试阅卷老师，请对学生的答案进行评分和反馈。

【题型】{question['type']}
【题目】{question['content']}
【参考答案】{question['reference_answer']}
【满分】{question['score']}
【学生答案】{user_answer}

请严格返回如下格式：
Score: <0-15>
Feedback: <中文简短评价，指出语法/词汇/内容问题>
""".strip()

    return prompt


def main():
    if not check_ai():
        print("AI不可用：请检查 SILICONFLOW_API_KEY 是否正确配置")
        return

    prompt = build_mock_prompt()
    result = call_ai_full(prompt)

    if not result or result.get("status") != "success":
        print("AI调用失败：", result)
        return

    print("模型：", result.get("model"))
    print("返回内容：\n", result.get("content"))
    print("用量：", result.get("usage"))


if __name__ == "__main__":
    main()
