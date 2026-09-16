"""论文下载系统配置文件

所有超参数和配置集中在此文件中，业务代码通过 import 引用。
修改此文件即可调整行为，无需改动业务代码。
"""
from pathlib import Path

# ========== 路径配置 ==========
# PDF 下载保存目录（可修改为实际路径，默认下载到脚本所在目录的 download 子目录）
DOWNLOAD_DIR = Path.home() / "paper_downloads"
# 历史记录文件（记录已下载论文 ID，避免重复下载）
HISTORY_FILE = Path(__file__).parent / "downloaded_ids.txt"

# ========== 每日下载数量 ==========
DAILY_LIMIT = 5

# ========== 搜索关键词（多模态 + Agent 方向）==========
SEARCH_QUERIES = [
    # 多模态方向
    "multimodal large language model",
    "vision language model",
    "multimodal understanding generation",
    "visual instruction tuning",
    # Agent方向
    "AI agent",
    "autonomous agent",
    "LLM-based agent",
    "multi-agent system",
    "tool use language model",
    "embodied agent reasoning",
    "agentic workflow",
    # 交叉方向
    "multimodal agent",
    "visual grounding agent",
    "multimodal reasoning planning",
]

# ========== arXiv 分类（CS相关）===========
ARXIV_CATEGORIES = [
    "cs.CL",  # Computation and Language
    "cs.CV",  # Computer Vision
    "cs.AI",  # Artificial Intelligence
    "cs.LG",  # Machine Learning
    "cs.MA",  # Multiagent Systems
    "cs.RO",  # Robotics
]

# ========== 期刊/会议筛选 ==========
# arXiv 论文备注中会标注已被哪些会议接收
TARGET_VENUES = [
    "NeurIPS", "ICML", "ICLR",
    "CVPR", "ICCV", "ECCV",
    "ACL", "EMNLP", "NAACL",
    "AAAI", "IJCAI",
    "COLM", "ICRA", "IROS",
]

# ========== arXiv API 配置 ==========
ARXIV_API_BASE = "http://export.arxiv.org/api/query"  # API 基础 URL
ARXIV_BATCH_SIZE = 100     # 每次请求的最大论文数（arXiv 限制最大 100）
ARXIV_API_TIMEOUT = 60     # 请求超时（秒）
ARXIV_API_RETRIES = 3      # 失败重试次数
ARXIV_RATE_LIMIT_WAIT = 5  # 限流等待基准时间（秒），实际等待 = attempt * 此值
ARXIV_FAIL_WAIT = 3        # 失败重试等待基准时间（秒），实际等待 = attempt * 此值

# ========== HTTP 请求配置 ==========
# 通用请求头（模拟浏览器）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
# 下载模块 User-Agent
DOWNLOAD_USER_AGENT = "PaperDownloader/1.0 (https://github.com/example/paper-downloader)"
# 下载 Session 重试次数
DOWNLOAD_RETRIES = 3
# 下载重试 backoff 因子
DOWNLOAD_RETRY_BACKOFF = 1
# 下载流式 chunk 大小（字节）
DOWNLOAD_CHUNK_SIZE = 65536
# 下载超时（秒）
DOWNLOAD_TIMEOUT = 120

# ========== 分类目录映射 ==========
# 论文分类 -> 子目录名（下载时按子目录存放）
CATEGORY_DIR_MAP = {
    "多模态+Agent": "多模态+Agent",
    "多模态": "多模态",
    "Agent": "Agent",
    "其他": "其他",
}

# ========== 采样配置 ==========
DAYS_BACK = 180             # 过去多少天内的论文视为"近期"
SAMPLE_TOTAL_SPAN = 2800    # 每个分类的总采样跨度（API offset 范围）
SAMPLE_WINDOWS = 8          # 每个分类的采样窗口数
SAMPLE_SLEEP = 1            # 采样窗口间的 sleep 间隔（秒）

# ========== 摘要抓取配置 ==========
ABSTRACT_FETCH_TIMEOUT = 30          # 请求超时（秒）
ABSTRACT_FETCH_DELAY_MIN = 0.3       # 请求间隔下限（秒）
ABSTRACT_FETCH_DELAY_MAX = 0.8       # 请求间隔上限（秒）
ABSTRACT_MAX_LENGTH = 500            # 摘要截断长度（字符）

# ========== 排序评分权重 ==========
SCORE_VENUE = 80                # 期刊/会议接收加分
SCORE_KNOWN_AUTHOR = 25         # 知名作者加分
SCORE_KNOWN_INSTITUTION = 10    # 知名机构加分
SCORE_KEYWORD = 15              # 关键词匹配加分（每个关键词）
SCORE_CROSS_MODAL_AGENT = 40    # 多模态+Agent 交叉加分
SCORE_CATEGORY = 5              # 分类加分

# 引用数加分阈值 [(引用数, 加分值), ...]
CITATION_THRESHOLDS = [
    (200, 80),
    (100, 60),
    (50,  40),
    (20,  25),
    (10,  15),
    (5,   8),
    (1,   3),
]

# ========== 排名初筛配置 ==========
RANK_PRE_SELECT = 50     # 初筛保留的候选数（无引用分数排序后取前 N 篇查引用）
RANK_FINAL_RETURN = 20   # 最终返回的候选数（给下载模块留跳过余量）

# ========== 知名学者名单（用于质量加分）==========
KNOWN_AUTHORS = {
    "andrew ng", "yann lecun", "geoffrey hinton", "yoshua bengio", "kaiming he",
    "fei-fei li", "josh tenenbaum", "pieter abbeel", "sergey Levine",
    "daphne koller", "christopher manning", "dan jurafsky", "zoubin ghahramani",
    "max welling", "bengio", "lecun", "hinton", "schmidhuber",
    "demis hassabis", "raia hadsell", "oriol vinyals", "noam shazeer",
    "ilan sutskever", "alex graves", "jeff dean", "quoc le", "grep b.", "ashish vaswani",
    "jacob devlin", "ming-wei chang", "percy liang",
}

# ========== 知名机构名单（用于质量加分）==========
KNOWN_INSTITUTIONS = {
    "google", "deepmind", "google deepmind", "meta ai", "facebook ai", "fair",
    "openai", "anthropic", "microsoft research", "ibm research",
    "stanford", "mit", "berkeley", "uc berkeley", "cmu", "carnegie mellon",
    "oxford", "cambridge", "eth", "epfl",
    "princeton", "harvard", "caltech", "cornell",
    "tsinghua", "peking", "beijing", "pku",
    "ucla", "nyu", "uwashington", "umich", "illinois",
    "max planck", "inria", "cnrs",
    "nvidia", "apple", "amazon",
}

# ========== 引用数查询配置 ==========
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/batch"  # 批量查询 API
CITATION_BATCH_SIZE = 20     # 每批查询篇数
CITATION_DELAY = 0.5         # 请求间隔（秒）
CITATION_RATE_LIMIT_WAIT = 10  # 限流等待时长（秒）
CITATION_TIMEOUT = 15        # 请求超时（秒）

# ========== 引文分类关键词 ==========
KEYWORDS_MULTIMODAL = [
    "multimodal", "vision language", "visual language",
    "image-text", "video-text", "visual grounding",
    "visual instruction", "vision-and-language",
]
KEYWORDS_AGENT = [
    "agent", "tool use", "tool calling", "function calling",
    "autonomous", "self-reflection", "self-improve",
    "multi-agent", "agentic", "react", "reasoning agent",
    "planning agent", "embodied",
]
KEYWORDS_SCORE = [
    "multimodal", "agent", "vision language", "tool use",
    "autonomous", "grounding", "reasoning", "planning",
]

# ========== 文件名处理 ==========
# 论文标题最大长度（字符数，超出部分截断）
FILENAME_MAX_LENGTH = 80
