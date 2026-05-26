import json
import sqlite3
from pathlib import Path
import random
from utils.exam_schema import normalize_exam_paper
from typing import List, Dict, Any, Optional
from datetime import datetime
import os
import re


class DatabaseManager:
    def __init__(self, db_path: str = None):
        # 检查是否在云端环境
        if db_path is None:
            # 在云端环境中使用临时路径
            if os.environ.get('SERVER_SOFTWARE', '').startswith('gunicorn') or \
               os.environ.get('DYNO') or \
               os.environ.get('STREAMLIT_ENV') or \
               os.environ.get('RAILWAY_DEPLOYMENT') or \
               os.environ.get('HOSTNAME', '').endswith('.herokuapp.com'):
                # 云端环境，使用临时路径
                self.db_path = os.path.join("/tmp", "english_app.db")
            else:
                # 本地环境
                self.db_path = "./local_database.db"
        else:
            self.db_path = db_path
            
        # 确保目录存在
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
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
                section_id TEXT,
                correct_answer TEXT,
                explanation TEXT,
                grading_status TEXT,
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
        """导入词库数据，如果没有则创建示例数据"""
        # 检查是否已有数据
        cursor.execute("SELECT COUNT(*) FROM word_bank_words")
        count = cursor.fetchone()[0]
        
        if count > 0:
            return count  # 已有数据，直接返回
        
        # 创建示例数据
        sample_words = [
            ("CET4", "vocabulary", "abandon", '{"definition": "to give up", "example": "He abandoned his plan."}'),
            ("CET4", "vocabulary", "benefit", '{"definition": "advantage", "example": "This has many benefits."}'),
            ("CET4", "vocabulary", "challenge", '{"definition": "difficulty", "example": "This is a challenge."}'),
            ("CET4", "vocabulary", "develop", '{"definition": "to grow", "example": "Skills develop over time."}'),
            ("CET4", "vocabulary", "efficient", '{"definition": "effective", "example": "An efficient method."}'),
            ("CET4", "vocabulary", "opportunity", '{"definition": "chance", "example": "Take this opportunity."}'),
            ("CET4", "vocabulary", "significant", '{"definition": "important", "example": "A significant improvement."}'),
            ("CET4", "vocabulary", "achieve", '{"definition": "to accomplish", "example": "Work hard to achieve goals."}'),
            ("CET4", "vocabulary", "contribute", '{"definition": "to give", "example": "Everyone can contribute."}'),
            ("CET4", "vocabulary", "evaluate", '{"definition": "to assess", "example": "Evaluate your progress."}'),
            ("CET6", "vocabulary", "innovation", '{"definition": "new idea", "example": "Technology drives innovation."}'),
            ("CET6", "vocabulary", "sustainable", '{"definition": "maintainable", "example": "Sustainable development."}'),
            ("CET6", "vocabulary", "globalization", '{"definition": "worldwide integration", "example": "Effects of globalization."}'),
            ("CET6", "vocabulary", "collaboration", '{"definition": "working together", "example": "Team collaboration."}'),
            ("CET6", "vocabulary", "perspective", '{"definition": "viewpoint", "example": "Different perspective."}'),
            ("CET6", "vocabulary", "implementation", '{"definition": "carrying out", "example": "Implementation of plans."}'),
            ("CET6", "vocabulary", "comprehensive", '{"definition": "complete", "example": "Comprehensive analysis."}'),
            ("CET6", "vocabulary", "integration", '{"definition": "combining", "example": "System integration."}'),
            ("CET6", "vocabulary", "diversity", '{"definition": "variety", "example": "Cultural diversity."}'),
            ("CET6", "vocabulary", "optimization", '{"definition": "improvement", "example": "Performance optimization."}')
        ]
        
        for level, variant, word, raw_json in sample_words:
            cursor.execute(
                "INSERT OR IGNORE INTO word_bank_words (level, variant, word, raw_json) VALUES (?, ?, ?, ?)",
                (level, variant, word, raw_json)
            )
        
        return len(sample_words)

    def get_user(self, username: str) -> Optional[Dict]:
        """获取用户信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, password, email FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "user_id": row[0],
                "username": row[1],
                "password": row[2],
                "email": row[3]
            }
        return None

    def create_user(self, username: str, password: str, email: str = "") -> int:
        """创建新用户"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, email) VALUES (?, ?, ?)",
            (username, password, email)
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id

    def get_wordbank_words(self, level: str, limit: int = 20) -> List[Dict]:
        """获取词库中的单词"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT word, raw_json FROM word_bank_words WHERE level = ? ORDER BY RANDOM() LIMIT ?",
            (level, limit)
        )
        rows = cursor.fetchall()
        conn.close()
        
        words = []
        for word, raw_json in rows:
            try:
                word_data = json.loads(raw_json) if raw_json else {}
                words.append({
                    "word": word,
                    "definition": word_data.get("definition", ""),
                    "example": word_data.get("example", "")
                })
            except json.JSONDecodeError:
                words.append({
                    "word": word,
                    "definition": "",
                    "example": ""
                })
        return words

    def get_words_by_difficulty(self, level: str, difficulty: int = 5, limit: int = 20) -> List[Dict]:
        """根据难度获取单词"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 根据难度调整查询策略，但目前我们使用随机选择
        cursor.execute(
            "SELECT word, raw_json FROM word_bank_words WHERE level = ? ORDER BY RANDOM() LIMIT ?",
            (level, limit)
        )
        rows = cursor.fetchall()
        conn.close()
        
        words = []
        for word, raw_json in rows:
            try:
                word_data = json.loads(raw_json) if raw_json else {}
                words.append({
                    "word": word,
                    "definition": word_data.get("definition", ""),
                    "example": word_data.get("example", "")
                })
            except json.JSONDecodeError:
                words.append({
                    "word": word,
                    "definition": "",
                    "example": ""
                })
        return words

    def get_recent_scores(self, user_id: int, level: str, recent_n: int = 10) -> List[Dict]:
        """获取最近的分数记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.total_score, s.total_possible, s.created_at, s.reading_score, s.reading_possible,
                   s.translation_score, s.translation_possible, s.writing_score, s.writing_possible
            FROM scores s
            JOIN exam_papers ep ON s.exam_id = ep.exam_id
            WHERE s.user_id = ? AND s.level = ?
            ORDER BY s.created_at DESC
            LIMIT ?
        """, (user_id, level, recent_n))
        rows = cursor.fetchall()
        conn.close()
        
        scores = []
        for row in rows:
            scores.append({
                "total_score": row[0],
                "total_possible": row[1],
                "created_at": row[2],
                "reading_score": row[3],
                "reading_possible": row[4],
                "translation_score": row[5],
                "translation_possible": row[6],
                "writing_score": row[7],
                "writing_possible": row[8]
            })
        return scores

    def get_user_performance_stats(self, user_id: int, level: str) -> Dict:
        """获取用户表现统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 获取总体统计
        cursor.execute("""
            SELECT 
                AVG(total_score * 1.0 / total_possible) as avg_accuracy,
                COUNT(*) as total_exams,
                MAX(total_score * 100.0 / total_possible) as max_score_percent,
                MIN(total_score * 100.0 / total_possible) as min_score_percent
            FROM scores s
            JOIN exam_papers ep ON s.exam_id = ep.exam_id
            WHERE s.user_id = ? AND s.level = ?
        """, (user_id, level))
        stats_row = cursor.fetchone()
        
        # 获取最近错误的单词
        cursor.execute("""
            SELECT ww.word, ww.error_count
            FROM wrong_words ww
            WHERE ww.user_id = ? AND ww.level = ?
            ORDER BY ww.error_count DESC, ww.last_error_time DESC
            LIMIT 10
        """, (user_id, level))
        wrong_words = cursor.fetchall()
        
        conn.close()
        
        return {
            "avg_accuracy": stats_row[0] if stats_row[0] is not None else 0,
            "total_exams": stats_row[1] if stats_row[1] is not None else 0,
            "max_score_percent": stats_row[2] if stats_row[2] is not None else 0,
            "min_score_percent": stats_row[3] if stats_row[3] is not None else 0,
            "wrong_words": [{"word": w[0], "count": w[1]} for w in wrong_words]
        }

    def record_word_quiz(self, user_id: int, level: str, word: str, is_correct: bool):
        """记录单词测试结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO word_quiz_records (user_id, level, word, is_correct) VALUES (?, ?, ?, ?)",
            (user_id, level, word, 1 if is_correct else 0)
        )
        conn.commit()
        conn.close()

    def record_wrong_word(self, user_id: int, level: str, word: str, source: str = "quiz"):
        """记录错词"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO wrong_words (user_id, level, word, source, error_count, last_error_time)
            VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, level, word, source) 
            DO UPDATE SET 
                error_count = error_count + 1,
                last_error_time = CURRENT_TIMESTAMP
        """, (user_id, level, word, source))
        conn.commit()
        conn.close()

    def get_wrong_words(self, user_id: int, level: str) -> List[Dict]:
        """获取用户的错词本"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT word, error_count, last_error_time, mastered
            FROM wrong_words
            WHERE user_id = ? AND level = ?
            ORDER BY error_count DESC, last_error_time DESC
        """, (user_id, level))
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "word": row[0],
                "error_count": row[1],
                "last_error_time": row[2],
                "mastered": bool(row[3])
            }
            for row in rows
        ]

    def mark_word_as_mastered(self, user_id: int, level: str, word: str):
        """标记单词为已掌握"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE wrong_words SET mastered = 1 WHERE user_id = ? AND level = ? AND word = ?",
            (user_id, level, word)
        )
        conn.commit()
        conn.close()

    def save_exam(self, user_id: int, level: str, exam_type: str, difficulty: int, paper_json: str) -> int:
        """保存试卷"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO exam_papers (user_id, level, exam_type, difficulty, paper_json, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (user_id, level, exam_type, difficulty, paper_json))
        exam_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return exam_id

    def update_exam_status(self, exam_id: int, status: str):
        """更新试卷状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if status == 'completed':
            cursor.execute(
                "UPDATE exam_papers SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE exam_id = ?",
                (status, exam_id)
            )
        else:
            cursor.execute(
                "UPDATE exam_papers SET status = ? WHERE exam_id = ?",
                (status, exam_id)
            )
        conn.commit()
        conn.close()

    def save_exam_answers(self, exam_id: int, answers_json: str):
        """保存试卷答案"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE exam_papers SET answers_json = ? WHERE exam_id = ?",
            (answers_json, exam_id)
        )
        conn.commit()
        conn.close()

    def get_user_exams(self, user_id: int) -> List[Dict]:
        """获取用户的历史试卷"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT exam_id, level, exam_type, difficulty, status, created_at, completed_at
            FROM exam_papers
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "exam_id": row[0],
                "level": row[1],
                "exam_type": row[2],
                "difficulty": row[3],
                "status": row[4],
                "created_at": row[5],
                "completed_at": row[6]
            }
            for row in rows
        ]

    def get_exam_by_id(self, exam_id: int) -> Optional[Dict]:
        """根据ID获取试卷"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT exam_id, paper_json, answers_json, level, exam_type, status FROM exam_papers WHERE exam_id = ?",
            (exam_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "exam_id": row[0],
                "paper_json": row[1],
                "answers_json": row[2],
                "level": row[3],
                "exam_type": row[4],
                "status": row[5]
            }
        return None

    def save_question_result(self, exam_id: int, question_id: str, question_type: str, 
                           user_answer: str, is_correct: bool, score_earned: float = 0, 
                           ai_feedback: str = "", section_id: str = "", 
                           correct_answer: str = "", explanation: str = "", 
                           grading_status: str = "graded"):
        """保存题目答题结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO exam_question_results 
            (exam_id, question_id, question_type, user_answer, is_correct, score_earned, 
             ai_feedback, section_id, correct_answer, explanation, grading_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (exam_id, question_id, question_type, user_answer, int(is_correct), score_earned,
              ai_feedback, section_id, correct_answer, explanation, grading_status))
        conn.commit()
        conn.close()

    def get_exam_results(self, exam_id: int) -> List[Dict]:
        """获取试卷答题结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT question_id, question_type, user_answer, is_correct, score_earned, 
                   ai_feedback, section_id, correct_answer, explanation, grading_status
            FROM exam_question_results
            WHERE exam_id = ?
            ORDER BY question_id
        """, (exam_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "question_id": row[0],
                "question_type": row[1],
                "user_answer": row[2],
                "is_correct": bool(row[3]),
                "score_earned": row[4],
                "ai_feedback": row[5],
                "section_id": row[6],
                "correct_answer": row[7],
                "explanation": row[8],
                "grading_status": row[9]
            }
            for row in rows
        ]

    def save_score(self, user_id: int, level: str, exam_id: int, total_score: int, 
                  total_possible: int, reading_score: int = None, reading_possible: int = None,
                  translation_score: int = None, translation_possible: int = None,
                  writing_score: int = None, writing_possible: int = None):
        """保存考试成绩"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scores 
            (user_id, level, exam_id, total_score, total_possible,
             reading_score, reading_possible, translation_score, translation_possible,
             writing_score, writing_possible)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, level, exam_id, total_score, total_possible,
              reading_score, reading_possible, translation_score, translation_possible,
              writing_score, writing_possible))
        conn.commit()
        conn.close()

    def get_user_scores(self, user_id: int, level: str = None) -> List[Dict]:
        """获取用户成绩记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if level:
            cursor.execute("""
                SELECT s.total_score, s.total_possible, s.created_at, ep.exam_type, ep.difficulty
                FROM scores s
                JOIN exam_papers ep ON s.exam_id = ep.exam_id
                WHERE s.user_id = ? AND s.level = ?
                ORDER BY s.created_at DESC
                LIMIT 50
            """, (user_id, level))
        else:
            cursor.execute("""
                SELECT s.total_score, s.total_possible, s.created_at, s.level, ep.exam_type, ep.difficulty
                FROM scores s
                JOIN exam_papers ep ON s.exam_id = ep.exam_id
                WHERE s.user_id = ?
                ORDER BY s.created_at DESC
                LIMIT 50
            """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        scores = []
        for row in rows:
            if level:
                scores.append({
                    "total_score": row[0],
                    "total_possible": row[1],
                    "created_at": row[2],
                    "exam_type": row[3],
                    "difficulty": row[4]
                })
            else:
                scores.append({
                    "total_score": row[0],
                    "total_possible": row[1],
                    "created_at": row[2],
                    "level": row[3],
                    "exam_type": row[4],
                    "difficulty": row[5]
                })
        
        return scores


# 创建全局实例
db = DatabaseManager()
