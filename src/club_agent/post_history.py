"""行銷歷史資料：累積每次上傳的貼文數據，產生月報與歷月比較。

- 貼文存在 posts 集合；同一篇貼文（平台＋日期＋時間＋內文開頭）重複上傳時合併，
  新上傳有填的數字會覆蓋舊的，新上傳空白的欄位保留舊值（例如上個月有填粉絲數、這次沒填）。
- 所以每個月只要上傳一次最新的匯出檔，歷史會自動累積。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .metrics import NUMBER_FIELDS, MetricsSummary, summarize
from .schemas import PostRecord

COLLECTION = "posts"


def post_key(p: PostRecord) -> str:
    raw = f"{p.platform}|{p.date}|{p.time}|{p.caption.strip()[:40]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _merge(old: PostRecord, new: PostRecord) -> PostRecord:
    update = {f: getattr(new, f) for f in NUMBER_FIELDS if getattr(new, f) is not None}
    update |= {f: getattr(new, f) for f in ("post_type", "topic", "caption") if getattr(new, f)}
    return old.model_copy(update=update)


def save_posts(store, club_id: str, posts: list[PostRecord]) -> tuple[int, int]:
    """存到歷史資料；回傳 (新增篇數, 更新篇數)。"""
    added = updated = 0
    for p in posts:
        key = post_key(p)
        existing = store.get_doc(club_id, COLLECTION, key)
        if existing:
            merged = _merge(PostRecord(**existing), p)
            if merged.model_dump() != existing:
                updated += 1
            store.put_doc(club_id, COLLECTION, key, merged.model_dump())
        else:
            store.put_doc(club_id, COLLECTION, key, p.model_dump())
            added += 1
    return added, updated


def list_history(store, club_id: str) -> list[PostRecord]:
    return sorted((PostRecord(**d) for d in store.list_docs(club_id, COLLECTION)), key=lambda p: (p.date, p.time))


def clear_history(store, club_id: str) -> None:
    for d in store.list_docs(club_id, COLLECTION):
        store.delete_doc(club_id, COLLECTION, post_key(PostRecord(**d)))


def months(posts: list[PostRecord]) -> list[str]:
    """有資料的月份（YYYY-MM），由新到舊。"""
    return sorted({p.date[:7] for p in posts}, reverse=True)


def previous_month(ym: str) -> str:
    year, month = int(ym[:4]), int(ym[5:7])
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


@dataclass
class MonthComparison:
    month: str
    previous: str
    current: MetricsSummary
    before: MetricsSummary | None

    def rows(self) -> list[tuple[str, str, str, str]]:
        """(指標, 本月, 上月, 變化)"""
        def num(v) -> str:
            return "—" if v is None else f"{v:,.0f}"

        def pct(v) -> str:
            return "—" if v is None else f"{v:.2%}"

        def change(a, b, as_points=False) -> str:
            if a is None or b is None:
                return "—"
            if as_points:
                return f"{(a - b) * 100:+.2f} 個百分點"
            return f"{(a - b) / b:+.1%}" if b else "—"

        c, b = self.current, self.before
        rows = [
            ("貼文數", f"{c.total_posts}", f"{b.total_posts}" if b else "—",
             f"{c.total_posts - b.total_posts:+d} 篇" if b else "—"),
            ("平均觸及", num(c.avg_reach), num(b.avg_reach) if b else "—", change(c.avg_reach, b.avg_reach if b else None)),
            ("平均互動率", pct(c.avg_engagement_rate), pct(b.avg_engagement_rate) if b else "—",
             change(c.avg_engagement_rate, b.avg_engagement_rate if b else None, as_points=True)),
        ]
        if c.follower_end is not None:
            prev_followers = b.follower_end if b else None
            rows.append(("月底粉絲數", num(c.follower_end), num(prev_followers),
                         f"{c.follower_end - prev_followers:+,d}" if prev_followers is not None else "—"))
        return rows

    def to_prompt_text(self) -> str:
        table = "\n".join(f"- {name}：本月 {now}，上月 {prev}，變化 {diff}" for name, now, prev, diff in self.rows())
        parts = [f"[本月與上月比較：{self.month} vs {self.previous}]", table, "", f"[本月（{self.month}）統計]", self.current.to_prompt_text()]
        if self.before:
            parts += ["", f"[上月（{self.previous}）統計]", self.before.to_prompt_text()]
        else:
            parts += ["", f"（沒有上月 {self.previous} 的資料，無法比較）"]
        return "\n".join(parts)


def compare_month(posts: list[PostRecord], ym: str) -> MonthComparison:
    prev = previous_month(ym)
    current = [p for p in posts if p.date.startswith(ym)]
    before = [p for p in posts if p.date.startswith(prev)]
    if not current:
        raise ValueError(f"{ym} 沒有貼文資料")
    return MonthComparison(ym, prev, summarize(current), summarize(before) if before else None)
