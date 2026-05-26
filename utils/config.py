# 配置文件：存放API密钥和其他敏感配置
# 注意：不要将此文件提交到版本控制系统

# 硅基流动API配置
SILICONFLOW_API_KEY = "sk-kgsplldfxeymammltilahmrwbfhozfpqyjlnjsjuyyrmmmzy"
SILICONFLOW_API_URL = "https://api.siliconflow.cn/v1/chat/completions"

# 模型配置
MODEL_DEEPSEEK_V3 = "deepseek-ai/DeepSeek-V3"  # 综合最强
DEFAULT_MODEL = MODEL_DEEPSEEK_V3

# 智谱GLM-4-Flash API配置（备用）
GLM_API_KEY = "your_glm_api_key_here"
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

# 数据库配置
DATABASE_PATH = "data/english_app.db"

# 词库路径
VOCAB_HIGH_FREQ = "data/vocab_high_freq.txt"
VOCAB_COMPLETE = "data/vocab_complete.txt"

# 教学大纲
SYLLABUS_PATH = "data/syllabus.txt"

# 其他配置
DEFAULT_DIFFICULTY = 5
MAX_RECENT_SCORES = 5