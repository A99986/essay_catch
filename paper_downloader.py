"""PDF 下载模块"""
import os
import re
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import DOWNLOAD_DIR, HISTORY_FILE, DAILY_LIMIT

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
        print(f"  [下载] {paper['title'][:60]}...", end="", flush=True)
        resp = session.get(paper["pdf_url"], timeout=120, stream=True)
        resp.raise_for_status()

        content = b""
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                content += chunk
                # 每下载 1MB 打印一个点以示进展
                if len(content) % (1024 * 1024) < 65536:
                    print(".", end="", flush=True)
        print()

        pdf_path.write_bytes(content)
        _save_downloaded_id(arxiv_id)
        print(f"  [完成] 保存到 {category_dir}/{pdf_path.name} ({len(content)//1024}KB)")
        return pdf_path
    except requests.RequestException as e:
        print(f"\n  [失败] {paper['title'][:60]}... {e}")
        return None


def download_papers(papers: list[dict], target: int = None) -> list[Path]:
    """批量下载论文，跳过已下载，直到凑满 target 篇（默认 DAILY_LIMIT）"""
    if target is None:
        target = DAILY_LIMIT
    paths = []
    for p in papers:
        if len(paths) >= target:
            break
        result = download_paper(p)
        if result:
            paths.append(result)
    if len(paths) < target:
        print(f"  [提示] 候选论文中未下载的不足 {target} 篇，实际下载 {len(paths)} 篇")
    return paths
