"""论文下载系统配置文件"""
from pathlib import Path

# ========== 下载配置 ==========
# 下载到桌面论文文件夹内的 Download 子目录
DOWNLOAD_DIR = Path(r"C:\Users\50464\Desktop\论文\Download")
# 历史记录（已下载论文ID，避免重复下载）
HISTORY_FILE = Path(__file__).parent / "downloaded_ids.txt"

# ========== 每日下载数量 ==========
DAILY_LIMIT = 1

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
# arXiv上的论文会标注是否被这些会议接收
TARGET_VENUES = [
    "NeurIPS", "ICML", "ICLR",
    "CVPR", "ICCV", "ECCV",
    "ACL", "EMNLP", "NAACL",
    "AAAI", "IJCAI",
    "COLM", "ICRA", "IROS",
]
 