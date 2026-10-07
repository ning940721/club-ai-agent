"""社群數據的確定性統計分析。

在交給數據診斷 Agent 之前，先用程式算出互動率、各主題／形式／時段的表現與
月度趨勢。LLM 只負責「解讀」這些數字，而不是自己計算，以降低 AI 幻覺。

資料可以不完整：只有日期一定要有，其他欄位不知道就空著。
空白代表「不知道」，不會當成 0——沒有觸及人數的貼文不計算互動率、沒有時間的貼文不列入時段分析，
並在「資料完整度」中告訴使用者與 AI 少了什麼、會影響哪些結論。
欄位名稱不必和範本一樣：中文欄位、IG／FB 匯出的英文欄位都會自動對應。
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import mean

from .schemas import PostRecord

WEEKDAYS_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
INTERACTION_FIELDS = ("likes", "comments", "shares", "saves")
NUMBER_FIELDS = ("reach", *INTERACTION_FIELDS, "followers")
PLATFORMS = ("Instagram", "Facebook", "Threads", "Dcard", "其他")

FIELD_LABELS = {
    "date": "日期",
    "time": "時間",
    "platform": "平台",
    "post_type": "形式",
    "topic": "主題",
    "reach": "觸及人數",
    "likes": "按讚",
    "comments": "留言",
    "shares": "分享",
    "saves": "收藏",
    "followers": "粉絲數",
    "caption": "內文",
}

# 自動對應欄位用的關鍵字（依序比對；日期先比對，「發佈時間」這類含日期的欄位會被當成日期，時間再從中拆出）
FIELD_KEYWORDS = {
    "date": ("date", "日期", "發佈時間", "發布時間", "發文時間", "publish time", "published", "created"),
    "time": ("time", "時間", "時段"),
    "platform": ("platform", "平台"),
    "post_type": ("post_type", "post type", "形式", "類型", "type", "格式"),
    "topic": ("topic", "主題", "分類", "category"),
    "reach": ("reach", "觸及"),
    "likes": ("likes", "按讚", "讚", "心情", "reactions", "like"),
    "comments": ("comments", "留言", "comment", "回覆"),
    "shares": ("shares", "分享", "轉發", "轉貼", "轉傳", "repost", "share"),
    "saves": ("saves", "收藏", "儲存", "save"),
    "followers": ("followers", "粉絲", "追蹤者", "追蹤人數", "follower"),
    "caption": ("caption", "內文", "說明", "標題", "description", "title", "message", "文案"),
}

TEMPLATE_CSV = (
    "日期,時間,平台,形式,主題,觸及人數,按讚,留言,分享,收藏,粉絲數,內文\n"
    "2026-09-01,21:00,Instagram,輪播,活動宣傳,850,60,5,4,12,1200,期初迎新宣傳\n"
    "2026-09-04,,Instagram,Reels,社課花絮,1320,95,8,,20,,不知道的欄位可以空著\n"
)

IMPACT = {
    "time": "沒有時間的貼文不列入發文時段分析",
    "platform": "不列入依平台的比較",
    "post_type": "不列入依貼文形式的比較",
    "topic": "不列入依主題的比較",
    "reach": "沒有觸及人數的貼文無法計算互動率，也不列入平均觸及",
    "likes": "互動率只用有填的互動數計算，可能略為低估",
    "comments": "互動率只用有填的互動數計算，可能略為低估",
    "shares": "互動率只用有填的互動數計算，可能略為低估",
    "saves": "互動率只用有填的互動數計算，可能略為低估",
    "followers": "無法分析粉絲成長",
    "caption": "AI 看不到貼文內容，只能依數字分析",
}


# ---------------------------------------------------------------------------
# 讀取與欄位對應
# ---------------------------------------------------------------------------


def decode_csv_bytes(data: bytes) -> str:
    """Excel 在 Windows 存的中文 CSV 常是 Big5（cp950），UTF-8 解不開時改用 cp950。"""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp950")


def read_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """讀 CSV：回傳 (欄位名稱, 每一列)。整列空白的會略過。"""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    columns = [c.strip() for c in (reader.fieldnames or []) if c and c.strip()]
    rows = []
    for row in reader:
        cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
        if any(cleaned.values()):
            rows.append(cleaned)
    return columns, rows


def guess_mapping(columns: list[str]) -> dict[str, str]:
    """依欄位名稱猜測對應：先找名稱完全相同的，再找包含關鍵字的；每個欄位只對應一次。"""
    mapping: dict[str, str] = {}
    lowered = {c: c.lower() for c in columns}
    for f in FIELD_KEYWORDS:
        exact = next((c for c in columns if lowered[c] in (f, FIELD_LABELS[f]) and c not in mapping.values()), None)
        if exact:
            mapping[f] = exact
    for f, words in FIELD_KEYWORDS.items():
        if f in mapping:
            continue
        for word in words:
            col = next((c for c in columns if c not in mapping.values() and word in lowered[c]), None)
            if col:
                mapping[f] = col
                break
    return mapping


def parse_number(value) -> int | None:
    """「1,234」「850 人」→ 數字；空白、「-」或看不懂的 → None（不知道）。"""
    text = re.sub(r"[,\s，人次篇]", "", str(value or ""))
    if text in ("", "-", "—", "–", "N/A", "n/a", "NA"):
        return None
    try:
        number = round(float(text))
    except ValueError:
        return None
    return number if number >= 0 else None


def parse_time(value) -> str | None:
    """「21:30」「9:05」「下午 3:20」「3:20 PM」→ HH:MM。"""
    text = str(value or "").strip()
    match = re.search(r"(上午|下午|晚上|AM|PM|am|pm)?\s*(\d{1,2})[:：](\d{2})(?::\d{2})?\s*(AM|PM|am|pm)?", text)
    if not match:
        return None
    hour, minute = int(match.group(2)), int(match.group(3))
    marker = (match.group(1) or match.group(4) or "").lower()
    if marker in ("下午", "晚上", "pm") and hour < 12:
        hour += 12
    if marker in ("上午", "am") and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_datetime(value) -> tuple[str | None, str | None]:
    """日期（可能連同時間）→ (YYYY-MM-DD, HH:MM)。支援 2026-03-02、2026/3/2 13:00、03/02/2026 13:00（IG／FB 匯出格式）。"""
    text = str(value or "").strip()
    day = None
    if match := re.search(r"(\d{4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})", text):
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        rest = text[match.end():]
    elif match := re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text):
        m, d, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        rest = text[match.end():]
    else:
        return None, None
    try:
        day = date(y, m, d).isoformat()
    except ValueError:
        return None, None
    return day, parse_time(rest)


def rows_to_posts(rows: list[dict[str, str]], mapping: dict[str, str], default_platform: str = "") -> tuple[list[PostRecord], list[str]]:
    """把表格轉成貼文；回傳 (貼文, 略過的原因)。只有日期是必填。"""
    posts, skipped = [], []
    for n, row in enumerate(rows, 2):  # 第 1 列是標題
        def get(f: str) -> str:
            return row.get(mapping.get(f, ""), "").strip() if mapping.get(f) else ""

        day, time_in_date = parse_datetime(get("date"))
        if day is None:
            skipped.append(f"第 {n} 列：日期空白或看不懂（{get('date') or '空白'}）")
            continue
        posts.append(
            PostRecord(
                date=day,
                time=parse_time(get("time")) or time_in_date or "",
                platform=get("platform") or default_platform,
                post_type=get("post_type"),
                topic=get("topic"),
                caption=get("caption"),
                **{f: parse_number(get(f)) for f in NUMBER_FIELDS},
            )
        )
    return posts, skipped


def parse_posts_csv(text: str, default_platform: str = "") -> list[PostRecord]:
    """自動對應欄位後讀取貼文（命令列與測試用）；找不到日期欄位時丟出 ValueError。"""
    columns, rows = read_table(text)
    mapping = guess_mapping(columns)
    if "date" not in mapping:
        raise ValueError("找不到日期欄位（欄位名稱可用 date、日期、發佈時間…）")
    return rows_to_posts(rows, mapping, default_platform)[0]


def load_posts_csv(path: str | Path) -> list[PostRecord]:
    return parse_posts_csv(decode_csv_bytes(Path(path).read_bytes()))


# ---------------------------------------------------------------------------
# 指標
# ---------------------------------------------------------------------------


def interactions(p: PostRecord) -> int | None:
    """有填的互動數加總；四項都沒填時為 None。"""
    known = [v for f in INTERACTION_FIELDS if (v := getattr(p, f)) is not None]
    return sum(known) if known else None


def engagement_rate(p: PostRecord) -> float | None:
    """互動率 = 總互動數 / 觸及人數；缺觸及人數或互動數時為 None（不知道），不是 0。"""
    total = interactions(p)
    if total is None or not p.reach:
        return None
    return total / p.reach


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.2%}"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"


@dataclass
class FieldCoverage:
    field: str
    label: str
    filled: int
    total: int

    @property
    def missing(self) -> int:
        return self.total - self.filled

    @property
    def impact(self) -> str:
        return IMPACT.get(self.field, "") if self.missing else ""

    def line(self) -> str:
        if self.filled == 0:
            return f"{self.label}：全部沒有資料（{IMPACT.get(self.field, '')}）"
        return f"{self.label}：{self.filled}/{self.total} 篇有資料（{IMPACT.get(self.field, '')}）"


def coverage(posts: list[PostRecord]) -> list[FieldCoverage]:
    """每個欄位有幾篇有資料（日期一定有，不列入）。"""
    out = []
    for f, label in FIELD_LABELS.items():
        if f == "date":
            continue
        filled = sum(1 for p in posts if getattr(p, f) not in (None, ""))
        out.append(FieldCoverage(f, label, filled, len(posts)))
    return out


@dataclass
class GroupStat:
    key: str
    posts: int
    avg_reach: float | None
    avg_engagement_rate: float | None

    def line(self) -> str:
        return f"{self.key}: {self.posts} 篇, 平均觸及 {_num(self.avg_reach)}, 平均互動率 {_pct(self.avg_engagement_rate)}"


@dataclass
class MetricsSummary:
    total_posts: int
    date_range: tuple[str, str]
    avg_reach: float | None
    avg_engagement_rate: float | None
    follower_start: int | None
    follower_end: int | None
    by_month: list[GroupStat] = field(default_factory=list)
    by_topic: list[GroupStat] = field(default_factory=list)
    by_post_type: list[GroupStat] = field(default_factory=list)
    by_platform: list[GroupStat] = field(default_factory=list)
    by_weekday: list[GroupStat] = field(default_factory=list)
    by_hour: list[GroupStat] = field(default_factory=list)
    top_posts: list[str] = field(default_factory=list)
    bottom_posts: list[str] = field(default_factory=list)
    coverage: list[FieldCoverage] = field(default_factory=list)

    @property
    def reach_trend_percent(self) -> float | None:
        """最後一個月相對第一個月的平均觸及變化百分比。"""
        months = [m for m in self.by_month if m.avg_reach]
        if len(months) < 2:
            return None
        first, last = months[0].avg_reach, months[-1].avg_reach
        return (last - first) / first * 100

    @property
    def interaction_fields_used(self) -> list[str]:
        return [c.label for c in self.coverage if c.field in INTERACTION_FIELDS and c.filled]

    def to_prompt_text(self) -> str:
        """轉成給 LLM 閱讀的文字摘要。"""
        followers = (
            f"{self.follower_start} → {self.follower_end}" if self.follower_start is not None else "沒有資料"
        )
        lines = [
            f"分析期間：{self.date_range[0]} ~ {self.date_range[1]}，共 {self.total_posts} 篇貼文",
            f"整體平均觸及：{_num(self.avg_reach)}；整體平均互動率：{_pct(self.avg_engagement_rate)}",
            f"粉絲數：{followers}",
            f"互動率計算包含：{'、'.join(self.interaction_fields_used) or '（沒有互動數資料）'}",
        ]
        trend = self.reach_trend_percent
        if trend is not None:
            lines.append(f"首月至末月平均觸及變化：{trend:+.1f}%")
        gaps = [c for c in self.coverage if c.missing]
        if gaps:
            lines.append("\n[資料完整度]（空白代表不知道，未當成 0 計算）")
            lines.extend(f"- {c.line()}" for c in gaps)
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
        if k := keyfunc(p):
            buckets[k].append(p)
    stats = [
        GroupStat(
            key=k,
            posts=len(ps),
            avg_reach=_mean(p.reach for p in ps),
            avg_engagement_rate=_mean(engagement_rate(p) for p in ps),
        )
        for k, ps in buckets.items()
    ]
    if sort_by_key:
        return sorted(stats, key=lambda s: s.key)
    return sorted(stats, key=lambda s: (s.avg_engagement_rate is None, -(s.avg_engagement_rate or 0)))


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
    kind = "/".join(x for x in (p.platform, p.post_type, p.topic) if x) or "未分類"
    return f"{p.date} {kind} 觸及 {p.reach if p.reach is not None else '—'} 互動率 {_pct(engagement_rate(p))}「{caption}」"


def summarize(posts: list[PostRecord], top_n: int = 3) -> MetricsSummary:
    if not posts:
        raise ValueError("沒有貼文數據可供分析")
    ordered = sorted(posts, key=lambda p: (p.date, p.time))
    ranked = sorted((p for p in posts if engagement_rate(p) is not None), key=engagement_rate, reverse=True)
    with_followers = [p for p in ordered if p.followers]
    return MetricsSummary(
        total_posts=len(posts),
        date_range=(ordered[0].date, ordered[-1].date),
        avg_reach=_mean(p.reach for p in posts),
        avg_engagement_rate=_mean(engagement_rate(p) for p in posts),
        follower_start=with_followers[0].followers if with_followers else None,
        follower_end=with_followers[-1].followers if with_followers else None,
        by_month=_group(posts, lambda p: p.date[:7], sort_by_key=True),
        by_topic=_group(posts, lambda p: p.topic),
        by_post_type=_group(posts, lambda p: p.post_type),
        by_platform=_group(posts, lambda p: p.platform),
        by_weekday=_group(posts, _weekday),
        by_hour=_group(posts, _hour_bucket),
        top_posts=[_describe(p) for p in ranked[:top_n]],
        bottom_posts=[_describe(p) for p in ranked[-top_n:][::-1]] if len(ranked) > top_n else [],
        coverage=coverage(posts),
    )
