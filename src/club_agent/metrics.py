"""社群數據的確定性統計分析。

在交給數據診斷 Agent 之前，先用程式算出互動率、各主題／形式／時段的表現與
月度趨勢。LLM 只負責「解讀」這些數字，而不是自己計算，以降低 AI 幻覺。
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import mean

from .schemas import PostRecord

WEEKDAYS_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def load_posts_csv(path: str | Path) -> list[PostRecord]:
    """讀取貼文數據 CSV。欄位名稱需與 PostRecord 相同，缺少的數字欄位視為 0。"""
    posts: list[PostRecord] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cleaned = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            for key in ("reach", "likes", "comments", "shares", "saves", "followers"):
                cleaned[key] = int(float(cleaned.get(key) or 0))
            posts.append(PostRecord(**cleaned))
    return posts


def interactions(p: PostRecord) -> int:
    return p.likes + p.comments + p.shares + p.saves


def engagement_rate(p: PostRecord) -> float:
    """互動率 = 總互動數 / 觸及人數。"""
    return interactions(p) / p.reach if p.reach else 0.0


@dataclass
class GroupStat:
    key: str
    posts: int
    avg_reach: float
    avg_engagement_rate: float

    def line(self) -> str:
        return (
            f"{self.key}: {self.posts} 篇, 平均觸及 {self.avg_reach:.0f}, "
            f"平均互動率 {self.avg_engagement_rate:.2%}"
        )


@dataclass
class MetricsSummary:
    total_posts: int
    date_range: tuple[str, str]
    avg_reach: float
    avg_engagement_rate: float
    follower_start: int
    follower_end: int
    by_month: list[GroupStat] = field(default_factory=list)
    by_topic: list[GroupStat] = field(default_factory=list)
    by_post_type: list[GroupStat] = field(default_factory=list)
    by_platform: list[GroupStat] = field(default_factory=list)
    by_weekday: list[GroupStat] = field(default_factory=list)
    by_hour: list[GroupStat] = field(default_factory=list)
    top_posts: list[str] = field(default_factory=list)
    bottom_posts: list[str] = field(default_factory=list)

    @property
    def reach_trend_percent(self) -> float | None:
        """最後一個月相對第一個月的平均觸及變化百分比。"""
        if len(self.by_month) < 2 or not self.by_month[0].avg_reach:
            return None
        first, last = self.by_month[0].avg_reach, self.by_month[-1].avg_reach
        return (last - first) / first * 100

    def to_prompt_text(self) -> str:
        """轉成給 LLM 閱讀的文字摘要。"""
        lines = [
            f"分析期間：{self.date_range[0]} ~ {self.date_range[1]}，共 {self.total_posts} 篇貼文",
            f"整體平均觸及：{self.avg_reach:.0f}；整體平均互動率：{self.avg_engagement_rate:.2%}",
            f"粉絲數：{self.follower_start} → {self.follower_end}",
        ]
        trend = self.reach_trend_percent
        if trend is not None:
            lines.append(f"首月至末月平均觸及變化：{trend:+.1f}%")
        sections = [
            ("月度趨勢", self.by_month),
            ("依主題", self.by_topic),
            ("依貼文形式", self.by_post_type),
            ("依平台", self.by_platform),
            ("依星期", self.by_weekday),
            ("依發文時段", self.by_hour),
        ]
        for title, stats in sections:
            if stats:
                lines.append(f"\n[{title}]")
                lines.extend(f"- {s.line()}" for s in stats)
        if self.top_posts:
            lines.append("\n[互動率最高的貼文]")
            lines.extend(f"- {t}" for t in self.top_posts)
        if self.bottom_posts:
            lines.append("\n[互動率最低的貼文]")
            lines.extend(f"- {t}" for t in self.bottom_posts)
        return "\n".join(lines)


def _group(posts: list[PostRecord], keyfunc, sort_by_key: bool = False) -> list[GroupStat]:
    buckets: dict[str, list[PostRecord]] = defaultdict(list)
    for p in posts:
        k = keyfunc(p)
        if k:
            buckets[k].append(p)
    stats = [
        GroupStat(
            key=k,
            posts=len(ps),
            avg_reach=mean(p.reach for p in ps),
            avg_engagement_rate=mean(engagement_rate(p) for p in ps),
        )
        for k, ps in buckets.items()
    ]
    if sort_by_key:
        return sorted(stats, key=lambda s: s.key)
    return sorted(stats, key=lambda s: s.avg_engagement_rate, reverse=True)


def _weekday(p: PostRecord) -> str:
    try:
        return WEEKDAYS_ZH[date.fromisoformat(p.date).weekday()]
    except ValueError:
        return ""


def _hour_bucket(p: PostRecord) -> str:
    if not p.time:
        return ""
    try:
        hour = int(p.time.split(":")[0])
    except ValueError:
        return ""
    if 6 <= hour < 12:
        return "早上 06-12"
    if 12 <= hour < 17:
        return "下午 12-17"
    if 17 <= hour < 21:
        return "傍晚 17-21"
    return "深夜 21-06"


def _describe(p: PostRecord) -> str:
    caption = (p.caption[:30] + "…") if len(p.caption) > 30 else p.caption
    return (
        f"{p.date} {p.platform}/{p.post_type}/{p.topic} 觸及 {p.reach} "
        f"互動率 {engagement_rate(p):.2%}「{caption}」"
    )


def summarize(posts: list[PostRecord], top_n: int = 3) -> MetricsSummary:
    if not posts:
        raise ValueError("沒有貼文數據可供分析")
    ordered = sorted(posts, key=lambda p: (p.date, p.time))
    ranked = sorted(posts, key=engagement_rate, reverse=True)
    with_followers = [p for p in ordered if p.followers]
    return MetricsSummary(
        total_posts=len(posts),
        date_range=(ordered[0].date, ordered[-1].date),
        avg_reach=mean(p.reach for p in posts),
        avg_engagement_rate=mean(engagement_rate(p) for p in posts),
        follower_start=with_followers[0].followers if with_followers else 0,
        follower_end=with_followers[-1].followers if with_followers else 0,
        by_month=_group(posts, lambda p: p.date[:7], sort_by_key=True),
        by_topic=_group(posts, lambda p: p.topic),
        by_post_type=_group(posts, lambda p: p.post_type),
        by_platform=_group(posts, lambda p: p.platform),
        by_weekday=_group(posts, _weekday),
        by_hour=_group(posts, _hour_bucket),
        top_posts=[_describe(p) for p in ranked[:top_n]],
        bottom_posts=[_describe(p) for p in ranked[-top_n:][::-1]] if len(ranked) > top_n else [],
    )
