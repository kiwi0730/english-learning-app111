import json
import sqlite3
from pathlib import Path
import random
from utils.exam_schema import normalize_exam_paper
from typing import List, Dict, Any, Optional
from datetime import datetime
import re


class DatabaseManager:
    def __init__(self, db_path: str = "./local_database.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. 用户表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 2. 试卷表（完整版）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_papers (
                exam_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                level TEXT NOT NULL,
                exam_type TEXT,
                difficulty INTEGER DEFAULT 5,
                paper_json TEXT,
                answers_json TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        
        # 3. 答题记录表（精简版）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_question_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                question_type TEXT,
                user_answer TEXT,
                is_correct INTEGER,
                score_earned REAL DEFAULT 0,
                ai_feedback TEXT,
                answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(exam_id, question_id),
                FOREIGN KEY(exam_id) REFERENCES exam_papers(exam_id)
            )
        """)
        self._ensure_exam_question_results_columns(cursor)
        
        # 4. 成绩表（完整版）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                score_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                level TEXT NOT NULL,
                exam_id INTEGER NOT NULL,
                total_score INTEGER NOT NULL,
                total_possible INTEGER NOT NULL,
                reading_score INTEGER,
                reading_possible INTEGER,
                translation_score INTEGER,
                translation_possible INTEGER,
                writing_score INTEGER,
                writing_possible INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(exam_id) REFERENCES exam_papers(exam_id)
            )
        """)
        
        # 5. 错词本（完整版）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wrong_words (
                wrong_word_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                level TEXT NOT NULL,
                word TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'quiz',
                error_count INTEGER DEFAULT 1,
                last_error_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                mastered INTEGER DEFAULT 0,
                UNIQUE(user_id, level, word, source),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        
        # 6. 词库表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_bank_words (
                word_id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                variant TEXT NOT NULL,
                word TEXT NOT NULL,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(level, variant, word)
            )
        """)
        
        # 7. 单词考察记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_quiz_records (
                record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                level TEXT NOT NULL,
                word TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                quiz_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        
        self.import_wordbank_data(cursor)
        
        conn.commit()
        conn.close()

    def _ensure_exam_question_results_columns(self, cursor: sqlite3.Cursor) -> None:
        """兼容旧数据库，为题目结果表补充缺失字段。"""
        cursor.execute("PRAGMA table_info(exam_question_results)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        required_columns = {
            "section_id": "TEXT",
            "correct_answer": "TEXT",
            "explanation": "TEXT",
            "grading_status": "TEXT",
        }

        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                cursor.execute(f"ALTER TABLE exam_question_results ADD COLUMN {column_name} {column_type}")


    def import_wordbank_data(self, cursor: sqlite3.Cursor) -> int:
        """将四个词库文件一次性导入数据库，已存在数据则跳过"""
        cursor.execute("SELECT COUNT(*) FROM word_bank_words")
        if cursor.fetchone()[0] > 0:
            return 0

        data_dir = Path(__file__).parent.parent / "data"
        inserted_count = 0

        for level in ["CET4", "CET6"]:
            for variant in ["complete", "highquality"]:
                path = data_dir / f"{level}_{variant}.json"
                if not path.exists() and variant == "highquality":
                    alt_path = data_dir / f"{level}_highqualiy.json"
                    if alt_path.exists():
                        path = alt_path
                    else:
                        continue
                elif not path.exists():
                    continue

                try:
                    entries = self._load_wordbank_entries(path)
                    for entry in entries:
                        word = entry.get("word")
                        if not word:
                            continue

                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO word_bank_words (level, variant, word, raw_json)
                            VALUES (?, ?, ?, ?)
                            """,
                            (level, variant, word, json.dumps(entry, ensure_ascii=False))
                        )
                        inserted_count += cursor.rowcount

                    print(f"导入词库 {path.name}：{len(entries)} 条")
                except Exception as e:
                    print(f"导入词库 {path.name} 失败: {e}")

        return inserted_count

    def _load_wordbank_entries(self, path: Path) -> List[Dict[str, Any]]:
        """兼容逐行 JSON 和完整 JSON 的词库解析"""
        entries: List[Dict[str, Any]] = []

        def normalize_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            if not isinstance(item, dict):
                return None

            if "word" in item:
                return item

            if "headWord" in item:
                normalized = dict(item)
                normalized["word"] = item["headWord"]
                return normalized

            return None

        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    normalized = normalize_item(item)
                    if normalized:
                        entries.append(normalized)
                except json.JSONDecodeError:
                    entries = []
                    break

        if entries:
            return entries

        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            for item in data:
                normalized = normalize_item(item)
                if normalized:
                    entries.append(normalized)
        elif isinstance(data, dict):
            normalized = normalize_item(data)
            if normalized:
                entries.append(normalized)

        return entries

    def _row_to_word_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """把数据库行转换为词条字典"""
        data: Dict[str, Any] = {}
        if row["raw_json"]:
            try:
                data = json.loads(row["raw_json"])
            except json.JSONDecodeError:
                data = {}

        if not isinstance(data, dict):
            data = {}

        data.setdefault("word", row["word"])
        data.setdefault("level", row["level"])
        data.setdefault("variant", row["variant"])
        data.setdefault("word_id", row["word_id"])
        return data

    def _get_wordbank_rows(self, level: str, variant: str, limit: int = None) -> List[Dict[str, Any]]:
        """按级别和版本从数据库读取词条"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if limit is None:
            cursor.execute(
                """
                SELECT * FROM word_bank_words
                WHERE level = ? AND variant = ?
                ORDER BY word ASC
                """,
                (level, variant)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM word_bank_words
                WHERE level = ? AND variant = ?
                ORDER BY RANDOM()
                LIMIT ?
                """,
                (level, variant, limit)
            )

        results = cursor.fetchall()
        conn.close()
        return [self._row_to_word_dict(row) for row in results]

    def get_words_by_difficulty(self, level: str, difficulty: int, count: int = 20) -> List[Dict[str, Any]]:
        """根据难度从数据库随机获取单词。

        兼容两种输入：
        - 1~10 的整数难度：自动映射到 0.1~1.0
        - 0.1~1.0 的小数难度：直接按映射表处理
        """
        high_freq_ratio = self._difficulty_to_high_freq_ratio(difficulty)

        high_freq_count = int(count * high_freq_ratio)
        normal_count = count - high_freq_count

        words: List[Dict[str, Any]] = []
        words.extend(self._get_wordbank_rows(level, "highquality", high_freq_count))
        words.extend(self._get_wordbank_rows(level, "complete", normal_count))

        random.shuffle(words)
        return words[:count]

    def _difficulty_to_high_freq_ratio(self, difficulty: int) -> float:
        """把难度值转换为高频词占比。
        UI 1=最简单(90%高频词)，UI 10=最难(20%高频词)
        公式：内部值 = (11 - UI值) / 10
        """
        try:
            difficulty_value = float(difficulty)
        except (TypeError, ValueError):
            difficulty_value = 0.5

        if difficulty_value >= 1:
            difficulty_value = (11 - difficulty_value) / 10.0

        difficulty_value = round(difficulty_value, 1)
        difficulty_value = max(0.1, min(1.0, difficulty_value))

        ratio_map = {
            1.0: 0.90,
            0.9: 0.85,
            0.8: 0.80,
            0.7: 0.75,
            0.6: 0.70,
            0.5: 0.60,
            0.4: 0.50,
            0.3: 0.40,
            0.2: 0.30,
            0.1: 0.20,
        }

        if difficulty_value in ratio_map:
            return ratio_map[difficulty_value]

        if difficulty_value <= 0.1:
            return 0.20
        if difficulty_value >= 1.0:
            return 0.90

        sorted_points = sorted(ratio_map.items())
        lower_point = sorted_points[0]
        upper_point = sorted_points[-1]

        for index, point in enumerate(sorted_points[:-1]):
            next_point = sorted_points[index + 1]
            if point[0] <= difficulty_value <= next_point[0]:
                lower_point = point
                upper_point = next_point
                break

        lower_difficulty, lower_ratio = lower_point
        upper_difficulty, upper_ratio = upper_point
        if upper_difficulty == lower_difficulty:
            return lower_ratio

        progress = (difficulty_value - lower_difficulty) / (upper_difficulty - lower_difficulty)
        return lower_ratio + (upper_ratio - lower_ratio) * progress

    def get_all_words(self, level: str, variant: str = "complete") -> List[Dict[str, Any]]:
        """获取某等级某词库的全部单词"""
        return self._get_wordbank_rows(level, variant)

    def search_word(self, word: str, level: str = None) -> Optional[Dict[str, Any]]:
        """搜索单词定义"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if level:
            cursor.execute(
                """
                SELECT * FROM word_bank_words
                WHERE level = ? AND word = ?
                LIMIT 1
                """,
                (level, word)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM word_bank_words
                WHERE word = ?
                LIMIT 1
                """,
                (word,)
            )

        result = cursor.fetchone()
        conn.close()
        return self._row_to_word_dict(result) if result else None
    
    # ============ 用户相关操作 ============
    def create_user(self, username: str, password: str, email: str = None) -> int:
        """创建用户"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO users (username, password, email)
                VALUES (?, ?, ?)
            """, (username, password, email))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    
    def get_user(self, username: str) -> Optional[Dict]:
        """获取用户信息"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    
    # ============ 成绩相关操作 ============
    def save_score(self, user_id: int, level: str, total_score: float, total_possible: float, 
                 exam_id: int = None, reading_score: float = None, reading_possible: float = None,
                 translation_score: float = None, translation_possible: float = None,
                 writing_score: float = None, writing_possible: float = None) -> int:
        """保存成绩"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO scores (
                    user_id, level, exam_id,
                    total_score, total_possible,
                    reading_score, reading_possible,
                    translation_score, translation_possible,
                    writing_score, writing_possible
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, level, exam_id,
                total_score, total_possible,
                reading_score, reading_possible,
                translation_score, translation_possible,
                writing_score, writing_possible
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    
    def get_scores(self, user_id: int, level: str = None, limit: int = None, time_range: str = None) -> List[Dict]:
        """获取用户成绩记录"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        time_filters = {
            "最近一周": "-7 days",
            "最近一月": "-1 month",
            "最近三月": "-3 months"
        }
        time_delta = time_filters.get(time_range)

        if level:
            sql = """
                SELECT scores.*, scores.created_at AS date, exam_papers.difficulty AS difficulty
                FROM scores
                LEFT JOIN exam_papers ON scores.exam_id = exam_papers.exam_id
                WHERE scores.user_id = ? AND scores.level = ?
            """
            params = [user_id, level]
        else:
            sql = """
                SELECT scores.*, scores.created_at AS date, exam_papers.difficulty AS difficulty
                FROM scores
                LEFT JOIN exam_papers ON scores.exam_id = exam_papers.exam_id
                WHERE scores.user_id = ?
            """
            params = [user_id]

        if time_delta:
            sql += " AND scores.created_at >= datetime('now', ?)"
            params.append(time_delta)

        sql += " ORDER BY scores.created_at DESC"

        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        cursor.execute(sql, params)
        
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]

    def save_question_results(self, exam_id: int, question_results: List[Dict[str, Any]]) -> int:
        """保存或覆盖试卷题目结果"""
        if not question_results:
            return 0

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            for item in question_results:
                ai_feedback = item.get("ai_feedback")
                if isinstance(ai_feedback, (dict, list)):
                    ai_feedback = json.dumps(ai_feedback, ensure_ascii=False)

                cursor.execute(
                    """
                    INSERT INTO exam_question_results (
                        exam_id, question_id, question_type,
                        section_id, user_answer, correct_answer, explanation,
                        is_correct, score_earned, grading_status, ai_feedback, answered_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(exam_id, question_id) DO UPDATE SET
                        question_type = excluded.question_type,
                        section_id = excluded.section_id,
                        user_answer = excluded.user_answer,
                        correct_answer = excluded.correct_answer,
                        explanation = excluded.explanation,
                        is_correct = excluded.is_correct,
                        score_earned = excluded.score_earned,
                        grading_status = excluded.grading_status,
                        ai_feedback = excluded.ai_feedback,
                        answered_at = CURRENT_TIMESTAMP
                    """,
                    (
                        exam_id,
                        item.get("question_id"),
                        item.get("question_type"),
                        item.get("section_id"),
                        item.get("user_answer"),
                        item.get("correct_answer"),
                        item.get("explanation"),
                        item.get("is_correct"),
                        item.get("score_earned", 0),
                        item.get("grading_status"),
                        ai_feedback,
                    ),
                )
            conn.commit()
            return len(question_results)
        finally:
            conn.close()

    def get_question_results(self, exam_id: int) -> List[Dict[str, Any]]:
        """获取试卷题目结果"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM exam_question_results
            WHERE exam_id = ?
            ORDER BY result_id ASC
            """,
            (exam_id,),
        )
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]




    
    # ============ 错词相关操作 ============    
    def save_word_result(self, user_id: int, level: str, word: str, is_correct: bool, source: str = "quiz"):
        """保存单词答题结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 保存单词考察记录
        cursor.execute("""
            INSERT INTO word_quiz_records (user_id, level, word, is_correct)
            VALUES (?, ?, ?, ?)
        """, (user_id, level, word, 1 if is_correct else 0))
        
        # 更新错词本
        if not is_correct:
            # 检查是否已存在记录
            cursor.execute("""
                SELECT wrong_word_id FROM wrong_words 
                WHERE user_id = ? AND level = ? AND word = ? AND source = ?
            """, (user_id, level, word, source))
            
            if cursor.fetchone():
                # 如果存在，增加错误次数
                cursor.execute("""
                    UPDATE wrong_words 
                    SET error_count = error_count + 1, last_error_time = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND level = ? AND word = ? AND source = ?
                """, (user_id, level, word, source))
            else:
                # 如果不存在，插入新记录
                cursor.execute("""
                    INSERT INTO wrong_words (user_id, level, word, source, error_count)
                    VALUES (?, ?, ?, ?, 1)
                """, (user_id, level, word, source))
        else:
            # 如果答对了，标记为掌握
            cursor.execute("""
                UPDATE wrong_words 
                SET mastered = 1 
                WHERE user_id = ? AND level = ? AND word = ? AND source = ?
            """, (user_id, level, word, source))
        
        conn.commit()
        conn.close()
    
    def get_wrong_words(self, user_id: int, level: str) -> List[Dict]:
        """获取错词列表"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM wrong_words 
            WHERE user_id = ? AND level = ? AND mastered = 0
            ORDER BY error_count DESC
        """, (user_id, level))
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    def get_tested_words(self, user_id: int, level: str = None, limit: int = None) -> List[Dict]:
        """获取已考察过的单词列表。
        
        Args:
            user_id: 用户ID
            level: 级别（CET4/CET6），可选
            limit: 返回数量限制，默认返回全部
        
        Returns:
            单词列表，每项包含 word, is_correct, quiz_date 等字段
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if level:
            cursor.execute("""
                SELECT word, is_correct, quiz_date 
                FROM word_quiz_records 
                WHERE user_id = ? AND level = ?
                ORDER BY quiz_date DESC
                """ + ("LIMIT ?" if limit else ""),
                (user_id, level) + ((limit,) if limit else ()))
        else:
            cursor.execute("""
                SELECT word, is_correct, quiz_date 
                FROM word_quiz_records 
                WHERE user_id = ?
                ORDER BY quiz_date DESC
                """ + ("LIMIT ?" if limit else ""),
                (user_id,) + ((limit,) if limit else ()))
        
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    
    # ============ 试卷相关操作 ============
    def save_exam_paper(self, user_id: int, level: str, paper_json: Dict,
                       answers_json: Dict = None, feedback_json: Dict = None,
                       exam_id: int = None) -> int:
        """保存试卷。
    
        如果传入 exam_id，则更新对应试卷；否则插入新记录。
        """
        if exam_id is not None:
            return self.update_exam_paper(
                exam_id=exam_id,
                level=level,
                paper_json=paper_json,
                answers_json=answers_json,
                feedback_json=feedback_json,
            )
    
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            normalized_paper = normalize_exam_paper(paper_json if isinstance(paper_json, dict) else {})
            paper_info = normalized_paper.get("paper_info", {})
    
            difficulty = paper_info.get("difficulty", 5)
            exam_type = paper_info.get("exam_type", "normal_exam")
            level_value = level or paper_info.get("level", "CET4")
    
            cursor.execute("""
                INSERT INTO exam_papers (user_id, level, exam_type, difficulty, paper_json, answers_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                level_value,
                exam_type,
                difficulty,
                json.dumps(normalized_paper, ensure_ascii=False),
                json.dumps(answers_json, ensure_ascii=False) if answers_json is not None else None,
                "pending",
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    
    def update_exam_paper(self, exam_id: int, paper_json: Dict = None,
                          answers_json: Dict = None, feedback_json: Dict = None,
                          status: str = None, level: str = None) -> int:
        """更新已有试卷。"""
        fields = []
        values = []
    
        if paper_json is not None:
            normalized_paper = normalize_exam_paper(paper_json if isinstance(paper_json, dict) else {})
            fields.append("paper_json = ?")
            values.append(json.dumps(normalized_paper, ensure_ascii=False))
    
            paper_info = normalized_paper.get("paper_info", {})
            if paper_info.get("exam_type"):
                fields.append("exam_type = ?")
                values.append(paper_info.get("exam_type"))
    
        if answers_json is not None:
            fields.append("answers_json = ?")
            values.append(json.dumps(answers_json, ensure_ascii=False))
    
        if level is not None:
            fields.append("level = ?")
            values.append(level)
    
        if feedback_json is not None:
            pass
    
        if status is not None:
            fields.append("status = ?")
            values.append(status)
    
        if not fields:
            return exam_id
    
        values.append(exam_id)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"UPDATE exam_papers SET {', '.join(fields)} WHERE exam_id = ?",
                values,
            )
            conn.commit()
            return exam_id
        finally:
            conn.close()    
    def get_exam_papers(self, user_id: int, level: str = None) -> List[Dict]:
        """获取用户试卷列表"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if level:
            cursor.execute("""
                SELECT * FROM exam_papers 
                WHERE user_id = ? AND level = ? 
                ORDER BY created_at DESC
            """, (user_id, level))
        else:
            cursor.execute("""
                SELECT * FROM exam_papers 
                WHERE user_id = ? 
                ORDER BY created_at DESC
            """, (user_id,))
        
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]

    def get_exam_paper(self, exam_id: int) -> Optional[Dict[str, Any]]:
        """获取单份试卷记录。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM exam_papers
            WHERE exam_id = ?
            LIMIT 1
            """,
            (exam_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_latest_exam_paper(
        self,
        user_id: int,
        *,
        exam_type: Optional[str] = None,
        level: Optional[str] = None,
        status: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取用户最近一份试卷。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        conditions = ["user_id = ?"]
        params: List[Any] = [user_id]
        if exam_type:
            conditions.append("exam_type = ?")
            params.append(exam_type)
        if level:
            conditions.append("level = ?")
            params.append(level)
        if status:
            if isinstance(status, (list, tuple, set)):
                placeholders = ", ".join(["?"] * len(status))
                conditions.append(f"status IN ({placeholders})")
                params.extend(list(status))
            else:
                conditions.append("status = ?")
                params.append(status)

        sql = f"""
            SELECT * FROM exam_papers
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT 1
        """
        cursor.execute(sql, params)
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_ai_feedback(self, exam_id: int) -> Optional[Dict]:
        """获取试卷的题目级 AI 批改反馈。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT question_id, ai_feedback
            FROM exam_question_results
            WHERE exam_id = ? AND ai_feedback IS NOT NULL AND ai_feedback != ''
            ORDER BY result_id ASC
            """,
            (exam_id,),
        )
        result = cursor.fetchall()
        conn.close()
        
        if not result:
            return None

        feedback_map: Dict[str, Any] = {}
        for row in result:
            value = row["ai_feedback"]
            if isinstance(value, str):
                text = value.strip()
                if text.startswith("{") or text.startswith("["):
                    try:
                        value = json.loads(text)
                    except json.JSONDecodeError:
                        pass
            feedback_map[row["question_id"]] = value

        return feedback_map
    
    # ============ 难度推荐相关操作 ============
    def get_recent_scores(self, user_id: int, level: str, limit: int = 5) -> List[Dict]:
        """获取最近N次成绩"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT scores.*, exam_papers.difficulty AS difficulty
            FROM scores
            LEFT JOIN exam_papers ON scores.exam_id = exam_papers.exam_id
            WHERE scores.user_id = ? AND scores.level = ? 
            ORDER BY scores.created_at DESC 
            LIMIT ?
        """, (user_id, level, limit))
        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    
    def calculate_average_accuracy(self, user_id: int, level: str, limit: int = 5) -> float:
        """计算最近N次的平均正确率"""
        scores = self.get_recent_scores(user_id, level, limit)
        if not scores:
            return 0.0
        
        total_accuracy = 0
        for score in scores:
            if score["total_possible"] > 0:
                total_accuracy += score["total_score"] / score["total_possible"]
        
        return total_accuracy / len(scores) if scores else 0.0


# 全局数据库实例
db = DatabaseManager()