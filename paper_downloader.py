"""论文 PDF 下载模块

从 arXiv 批量下载 PDF，包含：
- 下载状态追踪（总数、成功、已存在、失败）
- 进度显示
- 按分类自动存放到对应子目录
- 更新历史记录
"""
import os
import re
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    DOWNLOAD_DIR, HISTORY_FILE,
    CATEGORY_DIR_MAP,
    HEADERS, DOWNLOAD_USER_AGENT,
    DOWNLOAD_RETRIES, DOWNLOAD_RETRY_BACKOFF,
    DOWNLOAD_CHUNK_SIZE, DOWNLOAD_TIMEOUT,
    FILENAME_MAX_LENGTH,
)


def _make_session() -> requests.Session:
    """创建配置好重试机制的 requests Session（仅供本模块内部调用）"""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.headers["User-Agent"] = DOWNLOAD_USER_AGENT

    retry_strategy = Retry(
        total=DOWNLOAD_RETRIES,
        backoff_factor=DOWNLOAD_RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _sanitize_filename(name: str, max_len: int = FILENAME_MAX_LENGTH) -> str:
    """清理字符串，使其适合作为文件名"""
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip()
    bad_repr = re.sub(r'[^\x20-\x7e]', "", name)
    name = " ".join(bad_repr.split())
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name if name else "untitled"


def download_papers(ranked: list[dict]) -> None:
    """下载排序后的论文 PDF"""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    downloaded_ids: set[str] = set()
    if HISTORY_FILE.exists():
        downloaded_ids = set(HISTORY_FILE.read_text(encoding="utf-8").strip().splitlines())

    session = _make_session()

    total = len(ranked)
    success = 0
    skipped = 0
    failed = 0

    print(f"\n{'='*60}")
    print(f"  开始批量下载，共 {total} 篇待处理")

    for i, paper in enumerate(ranked):
        arxiv_id = paper["arxiv_id"]
        title = paper["title"]
        if not arxiv_id or not title:
            continue

        # 跳过已下载的
        if arxiv_id in downloaded_ids:
            skipped += 1
            continue

        # 确定分类目录
        cat = classify_paper(paper)
        sub_dir_name = CATEGORY_DIR_MAP.get(cat, "其他")
        sub_dir = DOWNLOAD_DIR / sub_dir_name
        sub_dir.mkdir(parents=True, exist_ok=True)

        filename = f"[{arxiv_id}] {_sanitize_filename(title)}.pdf"
        filepath = sub_dir / filename

        # 尝试下载
        pdf_url = paper.get("pdf_url", f"https://arxiv.org/pdf/{arxiv_id}.pdf")
        print(f"\n  [{i + 1}/{total}] {title[:60]}...")
        print(f"         → {sub_dir_name}/{filename}")
        try:
            time.sleep(random.uniform(0.5, 1.2))
            resp = session.get(pdf_url, stream=True, timeout=DOWNLOAD_TIMEOUT)

            if not resp.ok:
                print(f"        HTTP {resp.status_code}，改用 arXiv 官方 URL...")
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                time.sleep(0.5)
                resp = session.get(pdf_url, stream=True, timeout=DOWNLOAD_TIMEOUT)

            if resp.ok:
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                # 写入历史记录
                with HISTORY_FILE.open("a", encoding="utf-8") as f:
                    f.write(arxiv_id + "\n")
                downloaded_ids.add(arxiv_id)
                success += 1
                print(f"        ✓ 下载成功")
            else:
                print(f"        HTTP {resp.status_code}，下载失败")
                failed += 1
        except (requests.RequestException, OSError) as e:
            print(f"        ✗ 异常: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"  下载完成！总: {total}, 成功: {success}, 跳过: {skipped}, 失败: {failed}")
    print(f"{'='*60}\n")


def classify_paper(paper: dict) -> str:
    """根据标题和摘要判断论文方向分类（内部简版，也可从 arxiv_fetcher import）"""
    text = (paper["title"] + " " + paper["summary"]).lower()
    is_multimodal = any(kw in text for kw in (
        "multimodal", "vision language", "visual language",
        "image-text", "video-text", "visual grounding",
        "visual instruction", "vision-and-language",
    ))
    is_agent = any(kw in text for kw in (
        "agent", "tool use", "tool calling", "function calling",
        "autonomous", "self-reflection", "self-improve",
        "multi-agent", "agentic", "react", "reasoning agent",
        "planning agent", "embodied",
    ))
    if is_multimodal and is_agent:
        return "多模态+Agent"
    elif is_multimodal:
        return "多模态"
    elif is_agent:
        return "Agent"
    else:
        return "其他"
