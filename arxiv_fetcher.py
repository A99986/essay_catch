"""arXiv 论文获取模块（基于 HTML 抓取，替代被屏蔽的 API）"""
import re
import time
import random
import warnings
from datetime import datetime, timedelta

import requests
import urllib3
from bs4 import BeautifulSoup

from config import SEARCH_QUERIES, ARXIV_CATEGORIES, TARGET_VENUES, DAILY_LIMIT

# 抑制 SSL 警告（本地网络环境问题）
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# 知名机构和学者（用于质量加分）
KNOWN_AUTHORS = {
    "andrew ng", "yann lecun", "geoffrey hinton", "yoshua bengio", "kaiming he",
    "fei-fei li", "josh tenenbaum", "pieter abbeel", "sergey levine",
    "daphne koller", "christopher manning", "dan jurafsky", "zoubin ghahramani",
    "max welling", "bengio", "lecun", "hinton", "schmidhuber",
    "demis hassabis", "raia hadsell", "oriol vinyals", "noam shazeer",
    "ilan sutskever", "alex graves", "jeff dean", "quoc le", "grep b.", "ashish vaswani",
    "jacob devlin", "ming-wei chang", "percy liang",
}

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

# 作者完整姓名的缓存，避免重复通知
_notified_authors: set = set()




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
    """对论文排序：优先推荐目标会议 + 引用数 + 关键词匹配度 + 机构/作者声誉"""

    # 先获取所有候选论文的引用数据
    enriched = _fetch_citation_counts(papers)

    def score(p: dict) -> float:
        s = 0.0

        # 会议接收（最高权重）
        if p["venue"]:
            s += 50

        # 引用数加分
        citations = p.get("citation_count", 0)
        if citations >= 50:
            s += 30
        elif citations >= 20:
            s += 20
        elif citations >= 5:
            s += 10
        elif citations >= 1:
            s += 5

        # 作者声誉加分
        author_text = " ".join(a.get("name", "") for a in p.get("authors", [])) if isinstance(p.get("authors"), list) and p["authors"] and isinstance(p["authors"][0], dict) else " ".join(p.get("authors", []))
        author_text = author_text.lower()
        known_authors_found = [n for n in KNOWN_AUTHORS if n in author_text]
        if known_authors_found:
            s += 25

        # 机构声誉加分
        inst_text = author_text + " " + p.get("summary", "").lower()
        for inst in KNOWN_INSTITUTIONS:
            if inst in inst_text:
                s += 10
                break

        # 关键词匹配
        text = (p["title"] + " " + p["summary"]).lower()
        keywords = [
            "multimodal", "agent", "vision language", "tool use",
            "autonomous", "grounding", "reasoning", "planning",
        ]
        for kw in keywords:
            if kw in text:
                s += 10

        if "multimodal" in text and "agent" in text:
            s += 20

        cat_text = " ".join(p.get("categories", [])).lower()
        if "cs.ai" in cat_text or "cs.cl" in cat_text or "cs.lg" in cat_text:
            s += 5

        return s

    ranked = sorted(enriched, key=score, reverse=True)
    return ranked[:DAILY_LIMIT]


def classify_paper(paper: dict) -> str:
    """根据标题和摘要判断论文方向分类"""
    text = (paper["title"] + " " + paper["summary"]).lower()

    is_multimodal = any(kw in text for kw in [
        "multimodal", "vision language", "visual language",
        "image-text", "video-text", "visual grounding",
        "visual instruction", "vision-and-language",
    ])
    is_agent = any(kw in text for kw in [
        "agent", "tool use", "tool calling", "function calling",
        "autonomous", "self-reflection", "self-improve",
        "multi-agent", "agentic", "react", "reasoning agent",
        "planning agent", "embodied",
    ])

    if is_multimodal and is_agent:
        return "多模态+Agent"
    elif is_multimodal:
        return "多模态"
    elif is_agent:
        return "Agent"
    else:
        return "其他"


def _fetch_citation_counts(papers: list[dict]) -> list[dict]:
    """通过 Semantic Scholar API 批量获取论文引用数"""
    if not papers:
        return papers

    arxiv_ids = [p["arxiv_id"] for p in papers]
    print(f"  查询引用数据（{len(arxiv_ids)} 篇）...")

    url = "https://api.semanticscholar.org/graph/v1/paper/batch"
    params = {"fields": "citationCount,title,externalIds"}

    id_map = {}
    for i in range(0, len(arxiv_ids), 50):
        batch = arxiv_ids[i:i + 50]
        payload = {"ids": [f"arXiv:{aid}" for aid in batch]}
        try:
            time.sleep(1)
            resp = requests.post(url, json=payload, params=params, timeout=15, verify=False)
            if resp.status_code == 429:
                print("    Semantic Scholar 限流，等待 5 秒...")
                time.sleep(5)
                resp = requests.post(url, json=payload, params=params, timeout=15, verify=False)
            if resp.ok:
                data = resp.json()
                for entry in data:
                    if entry is None:
                        continue
                    ext_ids = entry.get("externalIds", {}) or {}
                    aid = ext_ids.get("arXiv", "")
                    if aid:
                        id_map[aid] = entry.get("citationCount", 0)
            else:
                print(f"    S2 API 返回 {resp.status_code}")
        except requests.RequestException as e:
            print(f"    S2 API 请求失败: {e}")

    matched = 0
    for p in papers:
        aid = p["arxiv_id"]
        p["citation_count"] = id_map.get(aid, 0)
        if p["citation_count"] > 0:
            matched += 1

    print(f"  引用数据匹配: {matched}/{len(papers)} 篇有引用记录")
    return papers
