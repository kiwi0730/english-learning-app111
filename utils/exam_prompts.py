"""AI 试卷提示词构建。"""

from __future__ import annotations

import json

from utils.exam_schema import normalize_level

EXAM_SPECS = {
    "CET4": {
        "paper_name": "大学英语四级（CET-4）模拟试卷",
        "writing_format": "For this part, you are allowed 30 minutes to write an essay on the topic: [题目]. You should write at least 120 words but no more than 180 words.",
        "writing_type": "议论文或书信",
        "writing_topics": "校园生活、社会现象、教育话题",
        "banked_cloze_length": "200-250词",
        "banked_cloze_topics": "科普、社会、文化类",
        "long_reading_length": "约1000词",
        "long_reading_topics": "社会现象、科技发展、文化比较",
        "close_reading_length": "300-350词",
        "close_reading_topics": "第一篇为科技类，第二篇为人文类",
        "translation_length": "140-160字",
        "translation_topics": "中国文化、历史、社会发展",
        "close_reading_focus": "包含主旨题和细节题，尽量保持四级真题风格。",
        "translation_label": "汉译英",
    },
    "CET6": {
        "paper_name": "大学英语六级（CET-6）模拟试卷",
        "writing_format": "For this part, you are allowed 30 minutes to write an essay on the topic: [题目]. You should write at least 150 words but no more than 200 words.",
        "writing_type": "议论文或图表分析",
        "writing_topics": "社会热点、科技伦理、文化现象",
        "banked_cloze_length": "250-300词",
        "banked_cloze_topics": "学术、经济、心理类（词汇难度高于四级）",
        "long_reading_length": "约1200词",
        "long_reading_topics": "学术研究、社会评论、国际视野",
        "close_reading_length": "400-450词",
        "close_reading_topics": "第一篇为科技/经济类，第二篇为人文/哲学类",
        "translation_length": "180-200字",
        "translation_topics": "中国文化经典、历史事件、哲学思想",
        "close_reading_focus": "包含推理题、态度题、主旨题，难度略高于四级。",
        "translation_label": "汉译英",
    },
}


def _normalize_exam_level(level: str) -> str:
    value = str(level or "CET4").strip().upper()
    if value in {"4", "CET-4", "CET4"}:
        return "CET4"
    if value in {"6", "CET-6", "CET6"}:
        return "CET6"
    return "CET4"


def _get_exam_spec(level: str) -> dict:
    return EXAM_SPECS[_normalize_exam_level(level)]


def _format_word_sample(words) -> str:
    lines = []
    for index, item in enumerate(words, start=1):
        if not isinstance(item, dict):
            continue
        word = item.get("word", "")
        meaning = item.get("meaning") or item.get("cnMean") or item.get("translation") or item.get("explanation") or ""
        lines.append(f"{index}. {word} - {meaning}" if meaning else f"{index}. {word}")
    return "\n".join(lines)


def _get_difficulty_config(difficulty: int) -> dict:
    """
    根据难度等级 1-10 返回配置参数
    1最简单，10最难
    每一级独立配置，实现精准控制
    """
    # 难度1：最简单
    if difficulty == 1:
        return {
            "sentence_length": "6-10词",
            "inference_level": "literal",
            "inference_desc": "题干关键词在原文中直接出现，答案几乎与原文一致",
            "synonym_level": "直接匹配，使用原文原词",
            "vocabulary_difficulty": "基础词汇，四级核心词",
            "sentence_complexity": "简单句，主谓宾结构",
        }
    # 难度2
    elif difficulty == 2:
        return {
            "sentence_length": "7-11词",
            "inference_level": "literal",
            "inference_desc": "题干关键词在原文中直接出现，需要简单定位",
            "synonym_level": "直接匹配，使用原文原词",
            "vocabulary_difficulty": "基础词汇，少量四级词",
            "sentence_complexity": "简单句，可有简单修饰",
        }
    # 难度3
    elif difficulty == 3:
        return {
            "sentence_length": "8-12词",
            "inference_level": "literal",
            "inference_desc": "题干关键词在原文中直接出现，需快速定位",
            "synonym_level": "直接匹配，使用原文原词",
            "vocabulary_difficulty": "基础词汇，四级常见词",
            "sentence_complexity": "简单句，可有并列结构",
        }
    # 难度4
    elif difficulty == 4:
        return {
            "sentence_length": "10-14词",
            "inference_level": "literal_to_synonym",
            "inference_desc": "部分题目可直接定位，部分需要简单同义替换",
            "synonym_level": "基础同义替换，如常见词替换",
            "vocabulary_difficulty": "四级词汇，少量高频词",
            "sentence_complexity": "简单复合句",
        }
    # 难度5：中等基准
    elif difficulty == 5:
        return {
            "sentence_length": "12-16词",
            "inference_level": "synonym",
            "inference_desc": "需要同义替换，不能直接匹配原文词汇",
            "synonym_level": "简单同义替换，如重要词的同义词",
            "vocabulary_difficulty": "四级高频词，少量六级词",
            "sentence_complexity": "复合句，含一个从句",
        }
    # 难度6
    elif difficulty == 6:
        return {
            "sentence_length": "14-18词",
            "inference_level": "synonym",
            "inference_desc": "需要同义替换或短语重组",
            "synonym_level": "中等同义替换，短语替换",
            "vocabulary_difficulty": "四级+六级词汇混合",
            "sentence_complexity": "复合句，含定语从句",
        }
    # 难度7
    elif difficulty == 7:
        return {
            "sentence_length": "16-20词",
            "inference_level": "within_paragraph",
            "inference_desc": "需要在段落内推理，不能只看一句话",
            "synonym_level": "复杂同义替换或短语重组",
            "vocabulary_difficulty": "六级词汇为主",
            "sentence_complexity": "多重复合句",
        }
    # 难度8
    elif difficulty == 8:
        return {
            "sentence_length": "18-24词",
            "inference_level": "within_paragraph",
            "inference_desc": "需要在段落内综合推理，需理解上下文",
            "synonym_level": "复杂同义替换或句式转换",
            "vocabulary_difficulty": "六级词汇，含学术词",
            "sentence_complexity": "多重复合句，倒装/强调",
        }
    # 难度9
    elif difficulty == 9:
        return {
            "sentence_length": "20-28词",
            "inference_level": "cross_paragraph",
            "inference_desc": "需要跨段落综合信息，理解作者隐含态度",
            "synonym_level": "需要理解后总结，无法直接匹配",
            "vocabulary_difficulty": "六级+考研词汇",
            "sentence_complexity": "复杂长难句",
        }
    # 难度10：最难
    else:  # difficulty == 10
        return {
            "sentence_length": "24-32词",
            "inference_level": "cross_paragraph",
            "inference_desc": "需要跨段落推理+作者态度推断+隐含意义理解",
            "synonym_level": "需要深度理解后概括总结",
            "vocabulary_difficulty": "高级词汇，含熟词僻义",
            "sentence_complexity": "复杂长难句，多种语法现象",
        }
        


def _build_writing_prompt(level: str, words) -> str:
    spec = _get_exam_spec(level)
    
    # 预定义题目库，每次随机选择一个
    import random
    topics = {
        "CET4": [
            "The Importance of Developing Healthy Lifestyle Habits Among College Students",
            "The Impact of Social Media on Interpersonal Communication",
            "How to Balance Academic Study and Extracurricular Activities",
            "The Role of Critical Thinking in the Age of Information",
            "Ways to Bridge the Generation Gap Between Parents and Children",
            "The Benefits of Learning a Second Language",
            "How to Deal with Stress in College Life",
            "The Importance of Time Management for College Students",
            "The Value of Volunteer Work in Higher Education",
            "How to Build Good Relationships with Classmates and Teachers"
        ],
        "CET6": [
            "The Ethical Implications of Artificial Intelligence in Modern Society",
            "How to Balance Economic Development and Environmental Protection",
            "The Importance of Cultural Heritage Preservation in Globalization",
            "The Role of Innovation in Driving Economic Growth",
            "Ways to Address the Challenge of an Aging Population",
            "The Impact of Remote Work on Corporate Culture",
            "How to Foster Creativity and Critical Thinking in Education",
            "The Relationship Between Technological Progress and Employment",
            "The Importance of Financial Literacy for Young Adults",
            "How to Promote Sustainable Consumption in Daily Life"
        ]
    }
    
    level_key = "CET6" if normalize_level(level) == "CET6" else "CET4"
    topic_list = topics.get(level_key, topics["CET4"])
    selected_topic = random.choice(topic_list)
    
    return f"""
你正在生成{spec['paper_name']}的 Part I Writing。

请只输出 JSON，不要输出解释、Markdown 或代码块。

写作题目已经确定，请直接使用以下题目：
题目：{selected_topic}

JSON 格式：
{{
    "section": {{
        "section_id": "writing",
        "section_name": "Part I Writing",
        "section_type": "writing",
        "description": "作文题",
        "total_score": 15,
        "questions": [
            {{
                "question_id": "writing_1",
                "question_type": "writing",
                "stem": "Write an essay on the following topic.",
                "prompt": "For this part, you are allowed 30 minutes to write an essay on the topic: {selected_topic}. You should write at least 120 words but no more than 180 words.",
                "score": 15,
                "word_limit": "120-180"
            }}
        ]
    }}
}}

其他要求：
- 类型：{spec['writing_type']}
- 参考词汇（不要写进题面）：
{_format_word_sample(words)}
""".strip()

def _build_banked_cloze_prompt(level: str, difficulty: int, words) -> str:
    spec = _get_exam_spec(level)
    cfg = _get_difficulty_config(difficulty)
    return f"""
你正在生成{spec['paper_name']}的 Section A Banked Cloze。

【难度等级】{difficulty}/10（1最简单，10最难）
【句子长度】{cfg['sentence_length']}

请严格按照以下固定格式输出 **只输出JSON** ，不要输出解释、Markdown 或代码块。

输出格式（必须严格遵守）：
{{
    "section": {{
        "section_id": "banked_cloze",
        "section_name": "Section A Banked Cloze",
        "section_type": "banked_cloze",
        "description": "选词填空",
        "total_score": 10,
        "content": "【完整文章，约200-250词，空格用 1, 2, 3 ... 10 标记，例如：The 1 of technology is undeniable. It has 2 our lives in many ways...】",
        "questions": [
            {{
                "question_id": "banked_cloze_1",
                "question_type": "banked_cloze",
                "stem": "Choose the best word for blank 1.",
                "prompt": "Blank 1",
                "options": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O"],
                "score": 1
            }}
        ]
    }}
}}

【重要格式说明】
1. **content 字段**：只包含一篇完整文章，约{spec['banked_cloze_length']}，用数字 1-10 标记10个空格。
   - 正确示例："The 1 of technology is undeniable. It has 2 our lives in many ways..."
   - 错误示例：不要把选项列表或题目重复放在 content 中！

2. **questions 数组**：必须有10个元素，每个元素对应一个空格。
   - stem 必须明确是哪个空格，如 "Choose the best word for blank 1."
   - options 必须是15个选项的字母标签 ["A", "B", "C", ..., "O"]

3. **不要重复**：
   - content 中不要出现选项词
   - 不要在 content 后面重复列出选项
   - questions 中的每个题目只对应一个空格

题材：{spec['banked_cloze_topics']}
只生成这一 section，不要混入其他题型。
参考词汇：
{_format_word_sample(words)}
""".strip()


def _build_long_reading_prompt(level: str, difficulty: int, words) -> str:
    spec = _get_exam_spec(level)
    cfg = _get_difficulty_config(difficulty)
    return f"""
你正在生成{spec['paper_name']}的 Section B Long Reading（长篇阅读/段落匹配）。

【难度等级】{difficulty}/10
【句子长度】{cfg['sentence_length']}
【匹配复杂度】{cfg['synonym_level']}

请严格按照以下固定格式输出 **只输出JSON** ，不要输出解释、Markdown 或代码块。

输出格式（必须严格遵守）：
{{
    "section": {{
        "section_id": "long_reading",
        "section_name": "Section B Long Reading",
        "section_type": "long_reading",
        "description": "长篇阅读",
        "total_score": 10,
        "content": "【完整文章，约1000词，共8-10段，每段前标注段落号A、B、C...】",
        "questions": [
            {{
                "question_id": "long_reading_1",
                "question_type": "long_reading",
                "stem": "【句子题干，如：Which paragraph discusses the impact of technology on education?】",
                "prompt": "Statement 36",
                "options": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
                "score": 1
            }}
        ]
    }}
}}

【重要格式说明】
1. **content 字段**：只包含一篇完整文章，约{spec['long_reading_length']}，共8-10段。
   - 每段前必须标注段落号：A、B、C、D... 
   - 正确示例："A. Technology has changed our lives... B. Education is also affected..."
   - 错误示例：不要把句子题干放在 content 中！

2. **questions 数组**：必须有10个元素，每个元素对应一个句子匹配题。
   - stem 是句子题干，如 "Which paragraph discusses..."
   - prompt 是题号，如 "Statement 36"
   - options 是段落号 A-J（根据实际段落数量）

3. **不要重复**：
   - content 中不要出现句子题干
   - 不要在 content 后面重复列出句子
   - questions 中的每个题目只对应一个句子

题材：{spec['long_reading_topics']}
只生成这一 section，不要混入其他题型。
参考词汇：
{_format_word_sample(words)}
""".strip()


def _build_close_reading_prompt(level: str, article_no: int, difficulty: int, words) -> str:
    spec = _get_exam_spec(level)
    cfg = _get_difficulty_config(difficulty)
    
    if _normalize_exam_level(level) == "CET4":
        article_topic = "科技类" if article_no == 1 else "人文类"
    else:
        article_topic = "科技/经济类" if article_no == 1 else "人文/哲学类"

    return f"""
你正在生成{spec['paper_name']}的 Section C Close Reading（仔细阅读）第{article_no}篇。

【难度等级】{difficulty}/10（1最简单，10最难）
【句子长度】{cfg['sentence_length']}
【答案获取难度】{cfg['inference_desc']}
【题材】{article_topic}

请严格按照以下固定格式输出 **只输出JSON** ，不要输出解释、Markdown 或代码块。

输出格式（必须严格遵守）：
{{
    "section": {{
        "section_id": "close_reading_{article_no}",
        "section_name": "Section C Close Reading 第{article_no}篇",
        "section_type": "close_reading",
        "description": "仔细阅读",
        "total_score": 10,
        "content": "【完整文章，约{spec['close_reading_length']}】",
        "questions": [
            {{
                "question_id": "close_reading_{article_no}_1",
                "question_type": "close_reading",
                "stem": "【题干，如：According to the passage, what is the main idea?】",
                "prompt": "Choose the best answer.",
                "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
                "score": 2
            }}
        ]
    }}
}}

【重要格式说明】
1. **content 字段**：只包含一篇完整文章，约{spec['close_reading_length']}。
   - 正确示例："Technology has changed our daily lives in many ways..."
   - 错误示例：不要把题目选项放在 content 中！

2. **questions 数组**：必须有5个元素，每个元素对应一道选择题。
   - stem 是完整题干，包含问题和选项提示
   - prompt 是通用提示，如 "Choose the best answer."
   - options 是4个完整选项，如 ["A. ...", "B. ...", "C. ...", "D. ..."]

3. **不要重复**：
   - content 中不要出现选项内容
   - questions 中的每个题目是独立的

题材：{article_topic}
题目难度：{spec['close_reading_focus']}
只生成这一 section，不要混入其他题型。
参考词汇：
{_format_word_sample(words)}
""".strip()
def _build_translation_prompt(level: str, words) -> str:
    spec = _get_exam_spec(level)
    return f"""
你正在生成{spec['paper_name']}的 Part III Translation。

请只输出 JSON，不要输出解释、Markdown 或代码块。

JSON 格式：
{{
    "section": {{
        "section_id": "translation",
        "section_name": "Part III Translation",
        "section_type": "translation",
        "description": "翻译题",
        "total_score": 15,
        "questions": [
            {{
                "question_id": "translation_1",
                "question_type": "translation",
                "stem": "Translate the following paragraph into English.",
                "prompt": "Write your translation.",
                "passage": "...",
                "score": 15
            }}
        ]
    }}
}}

要求：
- 类型：{spec['translation_label']}。
- 话题：{spec['translation_topics']}。
- 只输出中文段落，约{spec['translation_length']}。
- 只生成这一 section，不要混入其他题型。
- 段落内容尽量与以下参考词汇相关联：
{_format_word_sample(words)}
""".strip()

def _build_answers_prompt(paper: dict) -> str:
    paper_info = paper.get("paper_info", {}) if isinstance(paper.get("paper_info"), dict) else {}
    sections_payload = []
    question_ids = []

    for section in paper.get("sections", []):
        if not isinstance(section, dict):
            continue

        questions_payload = []
        for question in section.get("questions", []):
            if not isinstance(question, dict):
                continue

            qid = str(question.get("question_id"))
            question_ids.append(qid)

            questions_payload.append(
                {
                    "question_id": qid,
                    "question_type": question.get("question_type"),
                    "stem": question.get("stem"),
                    "prompt": question.get("prompt"),
                    "passage": question.get("passage"),
                    "options": question.get("options"),
                    "score": question.get("score"),
                }
            )

        sections_payload.append(
            {
                "section_id": section.get("section_id"),
                "section_name": section.get("section_name"),
                "section_type": section.get("section_type"),
                "content": section.get("content"),
                "questions": questions_payload,
            }
        )

    payload = {
        "paper_info": {
            "paper_name": paper_info.get("paper_name"),
            "level": paper_info.get("level"),
            "difficulty": paper_info.get("difficulty"),
        },
        "sections": sections_payload,
    }

    return f"""
你是英语四六级试卷批改助手。请根据给定试卷，为每一道题生成标准答案与简要解析。

只输出 JSON，不要输出解释、Markdown、代码块或额外文本。

建议输出格式（优先使用 answers；若无法，允许 answer_key / analysis_key）：
{{
    "answers": {{
        "question_id": {{
            "correct_answer": "标准答案 / 标准翻译 / 作文范文",
            "explanation": "简要解析 / 评分要点"
        }}
    }}
}}

要求：
- 优先使用 answers 结构；若无法完整给出，可退回输出 answer_key 与 analysis_key。
- 每个 question_id 对应一个答案；不要重复或遗漏。
- 客观题给出唯一标准答案；主观题给出参考答案与评分要点。

question_id 列表（请从以下 key 选择）：
{json.dumps(question_ids, ensure_ascii=False)}

试卷数据：
{json.dumps(payload, ensure_ascii=False)}
""".strip()
def build_exam_prompts_module():
    """占位函数，避免空模块判断。"""
    return None