"""arXiv 论文获取模块（基于 HTML 抓取，替代被屏蔽的 API）"""
import re
import time
import random
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from config import SEARCH_QUERIES, ARXIV_CATEGORIES, TARGET_VENUES, DAILY_LIMIT

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _safe_get(url: str, retries: int = 3) -> str | None:
    """带重试的安全 HTTP GET 请求"""
    for attempt in range(retries):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                wait = (attempt + 1) * 8
                print(f"    被限流，等待 {wait} 秒...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except requests.RequestException as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 5
                print(f"    请求失败 ({e})，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                print(f"    放弃: {e}")
                return None
    return None


def _parse_list_page(html: str, cat: str) -> list[dict]:
    """解析 arXiv list 页面，提取论文基础信息"""
    soup = BeautifulSoup(html, "lxml")
    dts = soup.find_all("dt")
    dds = soup.find_all("dd")
    papers = []
    today = datetime.utcnow().strftime("%a, %d %b %Y")

    for dt, dd in zip(dts, dds):
        # 提取 arXiv ID
        dt_text = dt.get_text(strip=True)
        arxiv_id_match = re.search(r"arXiv:(\d{4}\.\d{4,5})", dt_text)
        if not arxiv_id_match:
            continue
        arxiv_id = arxiv_id_match.group(1)

        # 标题
        title_div = dd.find("div", class_="list-title")
        title = ""
        if title_div:
            title = title_div.get_text(strip=True).replace("Title:", "", 1).strip()

        # 作者
        authors_div = dd.find("div", class_="list-authors")
        authors = []
        if authors_div:
            for a in authors_div.find_all("a"):
                authors.append(a.get_text(strip=True))

        # 分类
        cats_div = dd.find("div", class_="list-subjects")
        categories = []
        if cats_div:
            raw = cats_div.get_text(strip=True)
            # 提取 cs.AI, cs.CL 等
            categories = re.findall(r"[a-z]+\.[A-Z]{2,}(?:\.[A-Z]{2,})?", raw)

        # 是否有会议标注（在 comments 中）
        comments_div = dd.find("div", class_="list-comments")
        venue = ""
        if comments_div:
            comments_text = comments_div.get_text(strip=True)
            for v in TARGET_VENUES:
                if v.lower() in comments_text.lower():
                    venue = v
                    break

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": "",  # 稍后通过摘要页面获取
            "authors": authors,
            "categories": categories,
            "published": today,
            "updated": today,
            "venue": venue,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        })

    return papers


def _fetch_abstracts(papers: list[dict]) -> list[dict]:
    """批量获取论文摘要（通过 abs 页面）"""
    for i, paper in enumerate(papers):
        if i > 0 and i % 5 == 0:
            print(f"    已获取 {i}/{len(papers)} 篇摘要...")
        html = _safe_get(paper["abs_url"])
        if html:
            soup = BeautifulSoup(html, "lxml")
            blockquote = soup.find("blockquote", class_="abstract")
            if blockquote:
                abstract_text = blockquote.get_text(strip=True).replace("Abstract:", "", 1).strip()
                paper["summary"] = abstract_text[:500]
            else:
                # fallback: mathjax 类
                abs_div = soup.select_one(".abstract.mathjax")
                if abs_div:
                    paper["summary"] = abs_div.get_text(strip=True).replace("Abstract:", "", 1).strip()[:500]
        time.sleep(random.uniform(0.3, 0.8))
    return papers


def fetch_recent_papers() -> list[dict]:
    """从 arXiv list 页面爬取最近论文"""
    all_papers: dict[str, dict] = {}

    # 从多个分类抓取
    categories_to_fetch = ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MA", "cs.RO"]
    for cat in categories_to_fetch:
        print(f"  抓取分类 {cat}...")
        html = _safe_get(f"https://arxiv.org/list/{cat}/recent?skip=0&show=50")
        if html:
            papers = _parse_list_page(html, cat)
            for p in papers:
                if p["arxiv_id"] not in all_papers:
                    all_papers[p["arxiv_id"]] = p
            print(f"    {cat}: 获取 {len(papers)} 篇")

    paper_list = list(all_papers.values())
    print(f"  去重后共 {len(paper_list)} 篇候选论文")

    # 获取摘要（只对最近24小时的论文，避免太多请求）
    if paper_list:
        print(f"  获取论文摘要...")
        paper_list = _fetch_abstracts(paper_list)

    return paper_list


def rank_papers(papers: list[dict]) -> list[dict]:
    """对论文排序：优先推荐目标会议 + 关键词匹配度高的"""

    def score(p: dict) -> float:
        s = 0.0
        if p["venue"]:
            s += 50
        text = (p["title"] + " " + p["summary"]).lower()
        keywords = [
            "multimodal", "agent", "vision language", "tool use",
            "autonomous", "grounding", "reasoning", "planning",
        ]
        for kw in keywords:
            if kw in text:
                s += 10

        # 多模态+agent 交叉加分
        if "multimodal" in text and "agent" in text:
            s += 20

        # 分类加分
        cat_text = " ".join(p.get("categories", [])).lower()
        if "cs.ai" in cat_text or "cs.cl" in cat_text or "cs.lg" in cat_text:
            s += 5
        return s

    ranked = sorted(papers, key=score, reverse=True)
    return ranked[:DAILY_LIMIT]
