"""
AI调用模块 - A负责
基于硅基流动平台，调用 DeepSeek-V3 模型
"""

import requests
import json
import logging
import time
from typing import Dict, Optional
from threading import Lock

# 从配置文件导入配置
from utils.config import (
    SILICONFLOW_API_KEY,
    SILICONFLOW_API_URL,
    MODEL_DEEPSEEK_V3,
    DEFAULT_MODEL
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AICaller:
    """AI 调用器 - 基于硅基流动"""
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AICaller, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.api_key = SILICONFLOW_API_KEY
            self.model = DEFAULT_MODEL
            self.session = None
            self.last_request_time = 0
            self.lock = Lock()
            self._init_session()
            self._initialized = True
    
    def _init_session(self):
        """初始化 Session，复用连接"""
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
    
    def _rate_limit(self):
        """频率控制：每秒最多 1 个请求"""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
            self.last_request_time = time.time()
    

    
    def is_available(self) -> bool:
        """检查 API Key 是否配置"""
        return bool(self.api_key) and self.api_key != "sk-xxx"
    
    def call(self, prompt: str) -> str:
        """返回纯文本，B/D 出卷用"""
        result = self.call_full(prompt)
        if result and result.get("status") == "success":
            return result.get("content", "")
        return ""
    
    def call_full(self, prompt: str, max_retries: int = 3, max_tokens: int = 2048, timeout: int = 240) -> Optional[Dict]:
        """返回完整结果，支持重试"""
        if not self.is_available():
            logger.warning("API Key 不可用，请填写正确的 SILICONFLOW_API_KEY")
            return None
        
        # 频率控制
        self._rate_limit()
        
        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        for attempt in range(max_retries):
            try:
                logger.info(f"调用 AI (尝试 {attempt + 1}/{max_retries})")
                response = self.session.post(SILICONFLOW_API_URL, json=data, timeout=timeout)
                
                if response.status_code == 200:
                    result = response.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    if content:
                        logger.info(f"调用成功，返回长度={len(content)}")
                        return {
                            "status": "success",
                            "content": content,
                            "model": self.model,
                            "usage": result.get("usage", {})
                        }
                    else:
                        logger.warning(f"返回内容为空 (尝试 {attempt + 1})")
                        
                elif response.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"限流 (429)，等待 {wait_time} 秒后重试")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"HTTP {response.status_code}: {response.text[:200]}")
                    return {"status": "error", "error": response.text}
                    
            except requests.exceptions.Timeout:
                logger.error(f"超时 (尝试 {attempt + 1})")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"调用失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        
        return {"status": "error", "error": "多次重试后仍然失败"}


# 全局实例
ai_caller = AICaller()


# ========== 对外接口 ==========

def call_ai(prompt: str) -> str:
    """B/D 用：返回纯文本"""
    return ai_caller.call(prompt)


def call_ai_full(prompt: str, max_retries: int = 3, max_tokens: int = 2048, timeout: int = 240) -> Optional[Dict]:
    """A 自己用：返回完整结果"""
    return ai_caller.call_full(prompt, max_retries=max_retries, max_tokens=max_tokens, timeout=timeout)


def check_ai() -> bool:
    """检查 AI 是否可用"""
    return ai_caller.is_available()