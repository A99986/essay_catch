"""arXiv 论文获取模块

基于官方 API 分页查询获取论文，支持：
- 跨分类、多窗口采样
- 多维度评分排序（期刊/会议、作者、机构、引用数）
- 引用数查询（Semantic Scholar API）
- 论文方向分类（多模态 / Agent / 交叉）
"""
import re
import time
import random
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

from config import (
    # arXiv API
    ARXIV_API_BASE, ARXIV_BATCH_SIZE, ARXIV_API_TIMEOUT,
    ARXIV_API_RETRIES, ARXIV_RATE_LIMIT_WAIT, ARXIV_FAIL_WAIT,
    # 采样
    DAYS_BACK, SAMPLE_TOTAL_SPAN, SAMPLE_WINDOWS, SAMPLE_SLEEP,
    # 摘要
    ABSTRACT_FETCH_TIMEOUT, ABSTRACT_FETCH_DELAY_MIN,
    ABSTRACT_FETCH_DELAY_MAX, ABSTRACT_MAX_LENGTH,
    # HTTP
    HEADERS,
    # 期刊
    TARGET_VENUES,
    # 排序评分
    SCORE_VENUE, SCORE_KNOWN_AUTHOR, SCORE_KNOWN_INSTITUTION,
    SCORE_KEYWORD, SCORE_CROSS_MODAL_AGENT, SCORE_CATEGORY,
    CITATION_THRESHOLDS,
    # 排名
    RANK_PRE_SELECT, RANK_FINAL_RETURN,
    # 知名学者和机构
    KNOWN_AUTHORS, KNOWN_INSTITUTIONS,
    # 引用查询
    SEMANTIC_SCHOLAR_API, CITATION_BATCH_SIZE,
    CITATION_DELAY, CITATION_RATE_LIMIT_WAIT, CITATION_TIMEOUT,
    # 关键词
    KEYWORDS_MULTIMODAL, KEYWORDS_AGENT, KEYWORDS_SCORE,
)

# arXiv API XML 命名空间
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# 作者完整姓名的缓存，避免重复通知
_notified_authors: set = set()


# ========== arXiv API 查询 ==========

def _api_query(query: str, start: int = 0, max_results: int = ARXIV_BATCH_SIZE,
               retries: int = ARXIV_API_RETRIES) -> str | None:
    """arXiv API 查询（带重试和限流处理）"""
    params = {
        "search_query": query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(ARXIV_API_BASE, params=params, timeout=ARXIV_API_TIMEOUT)
            if resp.status_code == 429:
                wait = (attempt + 1) * ARXIV_RATE_LIMIT_WAIT
                print(f"    API 限流，等待 {wait} 秒...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * ARXIV_FAIL_WAIT
                print(f"    API 请求失败 ({e})，{wait} 秒后重试...")
                time.sleep(wait)
            else:
                print(f"    放弃: {e}")
                return None
    return None


def _parse_api_entry(entry) -> dict:
    """解析 arXiv API 返回的单篇论文 XML entry"""
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

    # 从 comment 字段中提取期刊/会议信息
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


def _query_category_daterange(cat: str, start: int = 0,
                              max_results: int = ARXIV_BATCH_SIZE) -> list[dict]:
    """按分类查询论文"""
    query = f"cat:{cat}"
    xml_text = _api_query(query, start=start, max_results=max_results)
    if not xml_text:
        return []

    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", NS)
    papers = [_parse_api_entry(e) for e in entries]
    return papers


# ========== 摘要获取 ==========

def _fetch_abstracts(papers: list[dict]) -> list[dict]:
    """批量获取论文摘要（通过 HTML abs 页面）

    arXiv API 返回的摘要可能被截断，此函数从 HTML abs 页面获取完整摘要。
    只对精选后的少量论文调用，避免被限流。
    """
    for i, paper in enumerate(papers):
        if i > 0 and i % 5 == 0:
            print(f"    已获取 {i}/{len(papers)} 篇摘要...")
        try:
            time.sleep(random.uniform(ABSTRACT_FETCH_DELAY_MIN,
                                       ABSTRACT_FETCH_DELAY_MAX))
            resp = requests.get(paper["abs_url"], headers=HEADERS,
                                timeout=ABSTRACT_FETCH_TIMEOUT)
            if resp.ok:
                soup = BeautifulSoup(resp.text, "lxml")
                # 尝试两种常见的摘要容器选择器
                blockquote = soup.find("blockquote", class_="abstract")
                if blockquote:
                    abstract_text = blockquote.get_text(strip=True).replace("Abstract:", "", 1).strip()
                    paper["summary"] = abstract_text[:ABSTRACT_MAX_LENGTH]
                else:
                    abs_div = soup.select_one(".abstract.mathjax")
                    if abs_div:
                        paper["summary"] = abs_div.get_text(strip=True).replace("Abstract:", "", 1).strip()[:ABSTRACT_MAX_LENGTH]
        except requests.RequestException:
            pass
    return papers


# ========== 主获取流程 ==========

def fetch_recent_papers(days_back: int = DAYS_BACK) -> list[dict]:
    """通过 arXiv API 跨采样窗口随机获取约半年内的论文

    从 0~SAMPLE_TOTAL_SPAN 范围内随机取 SAMPLE_WINDOWS 个窗口，
    每个窗口取 ARXIV_BATCH_SIZE 篇，去重后返回。
    """
    all_papers: dict[str, dict] = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    categories_to_fetch = ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MA", "cs.RO"]
    starts = sorted(random.sample(range(0, SAMPLE_TOTAL_SPAN), SAMPLE_WINDOWS))

    for cat in categories_to_fetch:
        print(f"  查询 {cat}...")
        for start in starts:
            papers = _query_category_daterange(cat, start=start,
                                               max_results=ARXIV_BATCH_SIZE)
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
            time.sleep(SAMPLE_SLEEP)
        print(f"    {cat}: 获取中...")

    paper_list = list(all_papers.values())
    print(f"  去重后共 {len(paper_list)} 篇候选论文")
    return paper_list


# ========== 评分与排序 ==========

def _score_without_citations(p: dict) -> float:
    """无引用分数的评分（用于初筛）"""
    s = 0.0

    # 期刊/会议接收加分（最高权重）
    if p["venue"]:
        s += SCORE_VENUE

    # 作者声誉加分
    author_text = " ".join(
        a.get("name", "") for a in p.get("authors", [])
    ) if isinstance(p.get("authors"), list) and p["authors"] and isinstance(p["authors"][0], dict) else " ".join(
        p.get("authors", [])
    )
    author_text = author_text.lower()
    known_authors_found = [n for n in KNOWN_AUTHORS if n in author_text]
    if known_authors_found:
        s += SCORE_KNOWN_AUTHOR

    # 机构声誉加分
    inst_text = author_text + " " + p.get("summary", "").lower()
    for inst in KNOWN_INSTITUTIONS:
        if inst in inst_text:
            s += SCORE_KNOWN_INSTITUTION
            break

    # 关键词匹配（突出多模态+Agent 交叉方向）
    text = (p["title"] + " " + p["summary"]).lower()
    for kw in KEYWORDS_SCORE:
        if kw in text:
            s += SCORE_KEYWORD

    if "multimodal" in text and "agent" in text:
        s += SCORE_CROSS_MODAL_AGENT

    cat_text = " ".join(p.get("categories", [])).lower()
    if "cs.ai" in cat_text or "cs.cl" in cat_text or "cs.lg" in cat_text:
        s += SCORE_CATEGORY

    return s


def rank_papers(papers: list[dict]) -> list[dict]:
    """对论文排序：先用无引用分数初筛，再查引用数重排

    避免对全部候选论文查引用以节省 API 配额。
    """
    # 初筛：无引用分数排序，取前 RANK_PRE_SELECT
    pre_ranked = sorted(papers, key=_score_without_citations, reverse=True)[:RANK_PRE_SELECT]

    # 对初筛结果查引用数
    enriched = _fetch_citation_counts(pre_ranked)

    def score(p: dict) -> float:
        s = _score_without_citations(p)
        # 引用数加分（体现论文影响力）
        citations = p.get("citation_count", 0)
        for threshold, bonus in CITATION_THRESHOLDS:
            if citations >= threshold:
                s += bonus
                break
        return s

    ranked = sorted(enriched, key=score, reverse=True)
    return ranked[:RANK_FINAL_RETURN]


def classify_paper(paper: dict) -> str:
    """根据标题和摘要判断论文方向分类"""
    text = (paper["title"] + " " + paper["summary"]).lower()

    is_multimodal = any(kw in text for kw in KEYWORDS_MULTIMODAL)
    is_agent = any(kw in text for kw in KEYWORDS_AGENT)

    if is_multimodal and is_agent:
        return "多模态+Agent"
    elif is_multimodal:
        return "多模态"
    elif is_agent:
        return "Agent"
    else:
        return "其他"


# ========== 引用数查询 ==========

def _fetch_citation_counts(papers: list[dict]) -> list[dict]:
    """通过 Semantic Scholar API 批量获取论文引用数"""
    if not papers:
        return papers

    arxiv_ids = [p["arxiv_id"] for p in papers]
    print(f"  查询引用数据（{len(arxiv_ids)} 篇）...")

    params = {"fields": "citationCount,title,externalIds"}

    id_map = {}
    for i in range(0, len(arxiv_ids), CITATION_BATCH_SIZE):
        batch = arxiv_ids[i:i + CITATION_BATCH_SIZE]
        payload = {"ids": [f"arXiv:{aid}" for aid in batch]}
        for attempt in range(2):
            try:
                time.sleep(CITATION_DELAY)
                resp = requests.post(SEMANTIC_SCHOLAR_API, json=payload,
                                     params=params, timeout=CITATION_TIMEOUT)
                if resp.status_code == 429:
                    wait = CITATION_RATE_LIMIT_WAIT
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
