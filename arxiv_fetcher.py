"""arXiv 论文获取模块（基于 list 页面分页随机采样 + 摘要补充）"""
import re
import time
import random
import math
from datetime import datetime, timedelta, timezone

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



def _safe_get(url: str, retries: int = 3) -> str | None:
    """带重试的安全 HTTP GET 请求，返回纯文本"""
    for attempt in range(retries):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            resp = requests.get(url, headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"},
                                timeout=30)
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
            categories = re.findall(r"[a-z]+\.[A-Z]{2,}(?:\.[A-Z]{2,})?", raw)

        # 是否有会议标注
        comments_div = dd.find("div", class_="list-comments")
        venue = ""
        if comments_div:
            comments_text = comments_div.get_text(strip=True)
            for v in TARGET_VENUES:
                if v.lower() in comments_text.lower():
                    venue = v
                    break

        # 从元数据中提取发布日期
        published = ""
        meta_div = dd.find("div", class_="list-dateline")
        if meta_div:
            meta_text = meta_div.get_text(strip=True)
            m = re.search(r"Submitted\s+(\d+\s+\w+\s+\d{4})", meta_text)
            if m:
                published = m.group(1)

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": "",     # 稍后只对精选论文补充
            "authors": authors,
            "categories": categories,
            "published": published,
            "updated": "",
            "venue": venue,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        })

    return papers


def _sample_list_pages(cat: str, year: int, sample_count: int = 30) -> list[dict]:
    """从 arXiv 分类的年份列表页中随机采样 N 页，返回所有论文（不抓摘要）"""
    # 先获取第一页，找到总页数
    first_url = f"https://arxiv.org/list/{cat}/{year}?skip=0&show=50"
    html_text = _safe_get(first_url)
    if not html_text:
        return []

    papers = _parse_list_page(html_text, cat)

    # 从导航链接中提取所有 skip 值
    soup = BeautifulSoup(html_text, "lxml")
    skip_values = set()
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if f"/list/{cat}/{year}?skip=" in href:
            try:
                skip_val = int(href.split("skip=")[1].split("&")[0])
                skip_values.add(skip_val)
            except (ValueError, IndexError):
                pass

    if not skip_values:
        # 只有一页
        print(f"    {cat}: 仅1页，共 {len(papers)} 篇")
        return papers

    max_skip = max(skip_values)
    total_pages = max_skip // 50 + 1
    total_estimated = max_skip + 50
    print(f"    {cat}: 共约 {total_pages} 页 ~{total_estimated} 篇论文")

    # 随机采样 N 页（不包括已抓的第0页）
    available_pages = list(range(50, max_skip + 50, 50))
    if sample_count > len(available_pages):
        sample_count = len(available_pages)
    sampled_skips = random.sample(available_pages, sample_count)

    papers_by_id: dict[str, dict] = {p["arxiv_id"]: p for p in papers}

    # 抓取采样页面
    for i, skip in enumerate(sampled_skips):
        page_url = f"https://arxiv.org/list/{cat}/{year}?skip={skip}&show=50"
        page_html = _safe_get(page_url)
        if page_html:
            page_papers = _parse_list_page(page_html, cat)
            for p in page_papers:
                if p["arxiv_id"] not in papers_by_id:
                    papers_by_id[p["arxiv_id"]] = p
        if (i + 1) % 10 == 0:
            print(f"    已采样 {i+1}/{sample_count} 页...")

    result = list(papers_by_id.values())
    print(f"    {cat}: 采样后共 {len(result)} 篇去重论文")
    return result


def _fetch_abstracts(papers: list[dict]) -> list[dict]:
    """批量获取论文摘要"""
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
                abs_div = soup.select_one(".abstract.mathjax")
                if abs_div:
                    paper["summary"] = abs_div.get_text(strip=True).replace("Abstract:", "", 1).strip()[:500]
        time.sleep(random.uniform(0.3, 0.8))
    return papers


def fetch_recent_papers(days_back: int = 180) -> list[dict]:
    """从 arXiv 近半年的论文列表中随机采样，覆盖 nn 个分类"""
    all_papers: dict[str, dict] = {}

    # 从今天往前推半年确定年份
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days_back)
    year = start_date.year

    categories_to_fetch = ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.MA", "cs.RO"]
    for cat in categories_to_fetch:
        print(f"  采样分类 {cat}...")
        papers = _sample_list_pages(cat, year, sample_count=30)
        for p in papers:
            if p["arxiv_id"] not in all_papers:
                all_papers[p["arxiv_id"]] = p

    paper_list = list(all_papers.values())
    print(f"  去重后共 {len(paper_list)} 篇候选论文")
    return paper_list


def rank_papers(papers: list[dict]) -> list[dict]:
    """对论文排序：高权重给期刊/会议 + 引用数 + 作者/机构声誉 + 关键词匹配"""

    # 先获取引用数据
    enriched = _fetch_citation_counts(papers)

    def score(p: dict) -> float:
        s = 0.0

        # === 期刊/会议接收（最高权重）===
        # 已接收论文经过同行评审，价值已被验证
        if p["venue"]:
            s += 80

        # === 引用数（加权，体现论文影响力）===
        # 半年内的论文能积累引用通常说明其价值已被社区认可
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
