"""arXiv 论文获取模块（基于官方 API 分页查询 + 摘要补充）"""
import re
import time
import random
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

from config import SEARCH_QUERIES, ARXIV_CATEGORIES, TARGET_VENUES, DAILY_LIMIT

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

ARXIV_API_BASE = "http://export.arxiv.org/api/query"

# arXiv API XML 命名空间
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def _api_query(query: str, start: int = 0, max_results: int = 100, retries: int = 3) -> str | None:
    """arXiv API 查询（带重试）"""
    params = {
        "search_query": query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(ARXIV_API_BASE, params=params, timeout=60)
            if resp.status_code == 429:
                wait = (attempt + 1) * 5
                print(f"    API 限流，等待 {wait} 秒...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 3
                print(f"    API 请求失败 ({e})，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                print(f"    放弃: {e}")
                return None
    return None


def _parse_api_entry(entry) -> dict:
    """解析 arXiv API 返回的单篇论文 entry"""
    entry_id = entry.find("atom:id", NS).text.strip()
    arxiv_id_match = re.search(r"(\d{4}\.\d{4,5})", entry_id)
    arxiv_id = arxiv_id_match.group(1) if arxiv_id_match else ""

    title_el = entry.find("atom:title", NS)
    title = title_el.text.strip().replace("\n", " ").replace("  ", " ") if title_el is not None else ""

    summary_el = entry.find("atom:summary", NS)
    summary = summary_el.text.strip().replace("\n", " ").replace("  ", " ")[:500] if summary_el is not None else ""

    authors = []
    for author_el in entry.findall("atom:author", NS):
        name_el = author_el.find("atom:name", NS)
        if name_el is not None:
            authors.append(name_el.text.strip())

    categories = []
    for cat_el in entry.findall("atom:category", NS):
        term = cat_el.get("term", "")
        if term:
            categories.append(term)

    published_el = entry.find("atom:published", NS)
    published = published_el.text.strip()[:10] if published_el is not None else ""

    comment_el = entry.find("arxiv:comment", NS)
    venue = ""
    if comment_el is not None and comment_el.text:
        comment_text = comment_el.text
        for v in TARGET_VENUES:
            if v.lower() in comment_text.lower():
                venue = v
                break

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "summary": summary,
        "authors": authors,
        "categories": categories,
        "published": published,
        "updated": "",
        "venue": venue,
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def _query_category_daterange(cat: str, start: int = 0, max_results: int = 100) -> list[dict]:
    """按分类查询论文（API 不支持 submittedDate + cat 组合，在 Python 端过滤）"""
    query = f"cat:{cat}"
    xml_text = _api_query(query, start=start, max_results=max_results)
    if not xml_text:
        return []

    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", NS)
    papers = [_parse_api_entry(e) for e in entries]
    return papers


def _fetch_abstracts(papers: list[dict]) -> list[dict]:
    """批量获取论文摘要（通过 abs 页面）"""
    for i, paper in enumerate(papers):
        if i > 0 and i % 5 == 0:
            print(f"    已获取 {i}/{len(papers)} 篇摘要...")
        try:
            time.sleep(random.uniform(0.3, 0.8))
            resp = requests.get(paper["abs_url"], headers=HEADERS, timeout=30)
            if resp.ok:
                soup = BeautifulSoup(resp.text, "lxml")
                blockquote = soup.find("blockquote", class_="abstract")
                if blockquote:
                    abstract_text = blockquote.get_text(strip=True).replace("Abstract:", "", 1).strip()
                    paper["summary"] = abstract_text[:500]
                else:
                    abs_div = soup.select_one(".abstract.mathjax")
                    if abs_div:
                        paper["summary"] = abs_div.get_text(strip=True).replace("Abstract:", "", 1).strip()[:500]
        except requests.RequestException:
            pass
    return papers


def fetch_recent_papers(days_back: int = 180) -> list[dict]:
    """通过 arXiv API 跨采样窗口均匀获取半年内的论文"""
    all_papers: dict[str, dict] = {}
    from datetime import timedelta, datetime
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    categories_to_fetch = ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MA", "cs.RO"]
    # 每分类随机采样 8 个窗口，起始偏移随机，每个窗口取 100 篇
    total_span = 2800
    windows = 8
    starts = sorted(random.sample(range(0, total_span), windows))

    for cat in categories_to_fetch:
        print(f"  查询 {cat}...")
        for start in starts:
            papers = _query_category_daterange(cat, start=start, max_results=100)
            if not papers:
                continue
            for p in papers:
                pub = p.get("published", "")
                if pub:
                    try:
                        pub_dt = datetime.strptime(pub, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        if pub_dt < cutoff:
                            continue
                    except ValueError:
                        pass
                if p["arxiv_id"] not in all_papers:
                    all_papers[p["arxiv_id"]] = p
            time.sleep(1)
        print(f"    {cat}: 获取中...")

    paper_list = list(all_papers.values())
    print(f"  去重后共 {len(paper_list)} 篇候选论文")
    return paper_list


def _score_without_citations(p: dict) -> float:
    """无引用分数的评分（用于初筛）"""
    s = 0.0

    # === 期刊/会议接收（最高权重）===
    if p["venue"]:
        s += 80

    # === 作者声誉加分 ===
    author_text = " ".join(a.get("name", "") for a in p.get("authors", [])) if isinstance(p.get("authors"), list) and p["authors"] and isinstance(p["authors"][0], dict) else " ".join(p.get("authors", []))
    author_text = author_text.lower()
    known_authors_found = [n for n in KNOWN_AUTHORS if n in author_text]
    if known_authors_found:
        s += 25

    # === 机构声誉加分 ===
    inst_text = author_text + " " + p.get("summary", "").lower()
    for inst in KNOWN_INSTITUTIONS:
        if inst in inst_text:
            s += 10
            break

    # === 关键词匹配（突出多模态+Agent交叉方向）===
    text = (p["title"] + " " + p["summary"]).lower()
    keywords = [
        "multimodal", "agent", "vision language", "tool use",
        "autonomous", "grounding", "reasoning", "planning",
    ]
    for kw in keywords:
        if kw in text:
            s += 15

    if "multimodal" in text and "agent" in text:
        s += 40

    cat_text = " ".join(p.get("categories", [])).lower()
    if "cs.ai" in cat_text or "cs.cl" in cat_text or "cs.lg" in cat_text:
        s += 5

    return s


def rank_papers(papers: list[dict]) -> list[dict]:
    """
    对论文排序：先用无引用分数初筛 top 50，
    再查引用数重排，取最终 top 5。
    避免对全部候选论文查引用（节省 API 配额）。
    """

    # 初筛：无引用分数排序，取前 50
    pre_ranked = sorted(papers, key=_score_without_citations, reverse=True)[:50]

    # 对初筛结果查引用数
    enriched = _fetch_citation_counts(pre_ranked)

    def score(p: dict) -> float:
        s = _score_without_citations(p)

        # === 引用数（加权，体现论文影响力）===
        citations = p.get("citation_count", 0)
        if citations >= 200:
            s += 80
        elif citations >= 100:
            s += 60
        elif citations >= 50:
            s += 40
        elif citations >= 20:
            s += 25
        elif citations >= 10:
            s += 15
        elif citations >= 5:
            s += 8
        elif citations >= 1:
            s += 3

        return s

    ranked = sorted(enriched, key=score, reverse=True)
    return ranked[:20]


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
    for i in range(0, len(arxiv_ids), 20):
        batch = arxiv_ids[i:i + 20]
        payload = {"ids": [f"arXiv:{aid}" for aid in batch]}
        for attempt in range(2):
            try:
                time.sleep(0.5)
                resp = requests.post(url, json=payload, params=params, timeout=15)
                if resp.status_code == 429:
                    wait = 10
                    print(f"    Semantic Scholar 限流，等待 {wait} 秒...")
                    time.sleep(wait)
                    continue
                if resp.ok:
                    data = resp.json()
                    for entry in data:
                        if entry is None:
                            continue
                        ext_ids = entry.get("externalIds", {}) or {}
                        aid = ext_ids.get("ArXiv", "")
                        if aid:
                            id_map[aid] = entry.get("citationCount", 0)
                else:
                    print(f"    S2 API 返回 {resp.status_code}")
                break
            except requests.RequestException as e:
                print(f"    S2 API 请求失败: {e}")
                break

    matched = 0
    for p in papers:
        aid = p["arxiv_id"]
        p["citation_count"] = id_map.get(aid, 0)
        if p["citation_count"] > 0:
            matched += 1

    print(f"  引用数据匹配: {matched}/{len(papers)} 篇有引用记录")
    return papers
