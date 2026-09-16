"""AI论文自动下载系统 - 主入口

每日运行：从 arXiv 搜索多模态 + Agent 方向的论文，精选5篇下载到桌面。

用法：
    python main.py            # 执行一次下载
    python main.py --daily     # 持续运行（每24小时执行一次）
"""
import argparse
import sys
import time
from datetime import datetime, timezone

from arxiv_fetcher import fetch_recent_papers, rank_papers, classify_paper, _fetch_abstracts
from paper_downloader import download_papers
from config import DOWNLOAD_DIR, HISTORY_FILE


def run_once():
    """执行一次完整的获取 -> 排序 -> 下载流程"""
    print("=" * 60)
    print(f"AI论文自动下载系统 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"关注方向: 多模态 + Agent")
    print(f"保存目录: {DOWNLOAD_DIR}")
    print("=" * 60)

    # 1. 获取论文
    print("\n[1/3] 从 arXiv 获取论文...")
    papers = fetch_recent_papers()
    print(f"  共获取 {len(papers)} 篇候选论文")

    # 2. 排序精选
    print(f"\n[2/3] 精选排序，选取前5篇...")
    selected = rank_papers(papers)

    if not selected:
        print("  今日暂无新论文")
        return

    # 对精选论文补摘要（用于分类和展示）
    if not any(p.get("summary") for p in selected):
        print(f"  获取 {len(selected)} 篇精选论文的摘要...")
        selected = _fetch_abstracts(selected)

    for i, p in enumerate(selected, 1):
        p["category"] = classify_paper(p)
        venue_tag = f" [{p['venue']}]" if p["venue"] else ""
        print(f"  {i}. [{p['category']}]{venue_tag} {p['title'][:80]}")

    # 3. 下载
    print(f"\n[3/3] 开始下载 {len(selected)} 篇论文...")
    paths = download_papers(selected)

    # 统计
    print(f"\n{'=' * 60}")
    print(f"今日下载: {len(paths)}/{len(selected)} 篇")
    print(f"历史总计: {len(HISTORY_FILE.read_text(encoding='utf-8').strip().splitlines()) if HISTORY_FILE.exists() else 0} 篇")
    print(f"{'=' * 60}")


def run_daily(interval_hours: int = 24):
    """持续运行模式"""
    print(f"持续运行模式：每 {interval_hours} 小时执行一次")
    while True:
        run_once()
        next_run = interval_hours * 3600
        print(f"\n下次执行时间: {datetime.now(timezone.utc).timestamp() + next_run}")
        print(f"等待 {interval_hours} 小时后再次运行...\n")
        time.sleep(next_run)


def main():
    parser = argparse.ArgumentParser(description="AI论文自动下载系统")
    parser.add_argument(
        "--daily", action="store_true",
        help="持续运行模式（每24小时执行一次）"
    )
    parser.add_argument(
        "--interval", type=int, default=24,
        help="运行间隔（小时，默认24，需配合 --daily 使用）"
    )
    args = parser.parse_args()

    if args.daily:
        run_daily(args.interval)
    else:
        run_once()


if __name__ == "__main__":
    main()
