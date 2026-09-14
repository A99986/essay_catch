"""PDF 下载模块"""
import os
import re
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import DOWNLOAD_DIR, HISTORY_FILE

# 分类目录名映射
CATEGORY_DIR_MAP = {
    "多模态+Agent": "多模态+Agent",
    "多模态": "多模态",
    "Agent": "Agent",
    "其他": "其他",
}


def _load_downloaded_ids() -> set[str]:
    """加载已下载论文ID集合"""
    if not HISTORY_FILE.exists():
        return set()
    return set(HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines())


def _save_downloaded_id(arxiv_id: str):
    """保存已下载论文ID"""
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(arxiv_id + "\n")


def _make_session() -> requests.Session:
    """创建带重试机制的 HTTP session"""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.headers.update({
        "User-Agent": "PaperDownloader/1.0 (mailto:user@example.com)",
    })
    return session


def _sanitize_filename(title: str) -> str:
    """将论文标题处理为合法的文件名（去掉非法字符、限制长度）"""
    name = title.strip()
    name = re.sub(r'[\\/:*?"<>|]', ' ', name)
    name = re.sub(r'\s+', ' ', name)
    if len(name) > 80:
        name = name[:80].rstrip()
    return name


def download_paper(paper: dict) -> Path | None:
    """下载单篇论文 PDF，返回保存路径；若已存在或失败返回 None"""
    arxiv_id = paper["arxiv_id"]
    downloaded = _load_downloaded_ids()

    if arxiv_id in downloaded:
        print(f"  [跳过] {paper['title'][:60]}... (已下载)")
        return None

    # 按分类子目录存放
    category_dir = CATEGORY_DIR_MAP.get(paper.get("category", "其他"), "其他")
    target_dir = DOWNLOAD_DIR / category_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    file_name = _sanitize_filename(paper["title"])
    pdf_path = target_dir / f"{file_name}.pdf"

    # 如果标题文件名已存在，追加 arxiv_id 后缀避免冲突
    if pdf_path.exists():
        pdf_path = target_dir / f"{file_name}_{arxiv_id.replace('.', '_')}.pdf"

    session = _make_session()
    try:
        print(f"  [下载] {paper['title'][:60]}...")
        resp = session.get(paper["pdf_url"], timeout=60)
        resp.raise_for_status()

        pdf_path.write_bytes(resp.content)
        _save_downloaded_id(arxiv_id)
        print(f"  [完成] 保存到 {category_dir}/{pdf_path.name}")
        return pdf_path
    except requests.RequestException as e:
        print(f"  [失败] {paper['title'][:60]}... {e}")
        return None


def download_papers(papers: list[dict]) -> list[Path]:
    """批量下载论文"""
    paths = []
    for p in papers:
        result = download_paper(p)
        if result:
            paths.append(result)
    return paths
