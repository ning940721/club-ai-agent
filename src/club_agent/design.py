"""美宣（併入行銷）：各部門提出的設計需求單、社團視覺規範。

- 設計需求存在 design_requests 集合；未完成需求的截止日會出現在行事曆。
- 視覺規範存在 design 集合（id = brand），AI 產生設計說明時會參考。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from .schemas import DesignBrief

REQUESTS, GUIDE_COLLECTION, GUIDE_ID = "design_requests", "design", "brand"
STATUSES = ("待接單", "製作中", "待確認", "已完成", "取消")
OPEN_STATUSES = ("待接單", "製作中", "待確認")
SIZE_PRESETS = {
    "IG 貼文": "1080 × 1350 px（4:5）",
    "IG 限時動態": "1080 × 1920 px（9:16）",
    "Reels／短影音封面": "1080 × 1920 px（9:16）",
    "FB 貼文": "1080 × 1080 px 或 1200 × 630 px",
    "海報": "A3（297 × 420 mm）",
    "傳單": "A5（148 × 210 mm）",
    "簡報": "16:9",
    "其他": "",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DesignRequest(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    title: str
    department: str = Field(description="提出需求的部門代號")
    requester: str = ""
    kind: str = "IG 貼文"
    size: str = ""
    purpose: str = Field(default="", description="用途與想傳達的重點")
    copy_text: str = Field(default="", description="一定要放的文字：活動名稱、時間、地點、報名方式…")
    references: str = Field(default="", description="參考圖或連結")
    event: str = Field(default="", description="相關活動名稱")
    due: str = Field(default="", description="需要完成的日期 YYYY-MM-DD")
    status: str = "待接單"
    designer: str = ""
    note: str = ""
    brief: DesignBrief | None = None

    def due_date(self) -> date | None:
        try:
            return date.fromisoformat(self.due)
        except ValueError:
            return None

    def is_overdue(self, today: date) -> bool:
        d = self.due_date()
        return self.status in OPEN_STATUSES and d is not None and d < today

    def facts(self, dept_name=lambda k: k) -> str:
        return "\n".join([
            f"需求：{self.title}（{self.kind}，尺寸 {self.size or '未定'}）",
            f"提出部門：{dept_name(self.department)}",
            f"相關活動：{self.event or '無'}",
            f"用途與重點：{self.purpose or '未填'}",
            f"一定要放的文字：{self.copy_text or '未填'}",
            f"參考：{self.references or '無'}",
            f"截止日：{self.due or '未定'}",
        ])


class BrandColor(BaseModel):
    name: str = Field(description="顏色名稱，例如：主色、輔色、強調色")
    hex: str = Field(description="色碼，例如 #2D4A6B")
    usage: str = Field(description="用在哪裡")


class BrandGuide(BaseModel):
    colors: list[BrandColor] = Field(default_factory=list)
    heading_font: str = ""
    body_font: str = ""
    logo_rules: str = Field(default="", description="Logo 使用規則")
    tone: str = Field(default="", description="文案語氣")
    dos: list[str] = Field(default_factory=list, description="建議做法")
    donts: list[str] = Field(default_factory=list, description="避免的做法")
    updated_at: str = ""

    def is_empty(self) -> bool:
        return not (self.colors or self.heading_font or self.body_font or self.logo_rules or self.tone)

    def to_text(self) -> str:
        if self.is_empty():
            return "（社團還沒有視覺規範）"
        lines = [f"- {c.name} {c.hex}：{c.usage}" for c in self.colors]
        lines += [f"標題字體：{self.heading_font or '未定'}；內文字體：{self.body_font or '未定'}"]
        if self.logo_rules:
            lines.append(f"Logo：{self.logo_rules}")
        if self.tone:
            lines.append(f"語氣：{self.tone}")
        lines += [f"建議：{x}" for x in self.dos] + [f"避免：{x}" for x in self.donts]
        return "\n".join(lines)


def save_request(store, club_id: str, r: DesignRequest) -> None:
    store.put_doc(club_id, REQUESTS, r.id, r.model_copy(update={"updated_at": _now()}).model_dump())


def delete_request(store, club_id: str, request_id: str) -> None:
    store.delete_doc(club_id, REQUESTS, request_id)


def list_requests(store, club_id: str) -> list[DesignRequest]:
    """未完成在前，依截止日排序（沒有截止日的排最後）。"""
    items = [DesignRequest(**d) for d in store.list_docs(club_id, REQUESTS)]
    return sorted(items, key=lambda r: (r.status not in OPEN_STATUSES, r.due or "9999", r.created_at))


def get_guide(store, club_id: str) -> BrandGuide:
    data = store.get_doc(club_id, GUIDE_COLLECTION, GUIDE_ID)
    return BrandGuide(**data) if data else BrandGuide()


def save_guide(store, club_id: str, guide: BrandGuide) -> None:
    store.put_doc(club_id, GUIDE_COLLECTION, GUIDE_ID, guide.model_copy(update={"updated_at": _now()}).model_dump())


def _cell(text: object) -> str:
    return str(text).replace("|", "｜").replace("\n", " ")


def guide_markdown(club_name: str, g: BrandGuide) -> str:
    out = [f"# {club_name} 視覺規範", ""]
    if g.colors:
        out += ["## 品牌色", "| 名稱 | 色碼 | 用途 |", "|---|---|---|", *[f"| {_cell(c.name)} | {c.hex} | {_cell(c.usage)} |" for c in g.colors], ""]
    out += ["## 字體", f"- 標題：{g.heading_font or '【待補】'}", f"- 內文：{g.body_font or '【待補】'}", ""]
    if g.logo_rules:
        out += ["## Logo 使用", g.logo_rules, ""]
    if g.tone:
        out += ["## 文案語氣", g.tone, ""]
    if g.dos:
        out += ["## 建議做法", *[f"- {x}" for x in g.dos], ""]
    if g.donts:
        out += ["## 避免", *[f"- {x}" for x in g.donts], ""]
    return "\n".join(out).rstrip() + "\n"


def brief_markdown(r: DesignRequest, dept_name=lambda k: k) -> str:
    b = r.brief
    out = [f"# 設計說明：{r.title}", "", f"**類型：** {r.kind}　**尺寸：** {r.size or '【待補】'}　**截止：** {r.due or '【待補】'}　"
           f"**提出：** {dept_name(r.department)}{('（' + r.requester + '）') if r.requester else ''}", ""]
    if b is None:
        return "\n".join(out + ["（尚未產生）"]) + "\n"
    out += ["## 文案", f"**主標：** {b.headline}", "", f"**副標：** {b.subheadline}", "", b.body_copy, "",
            f"**行動呼籲：** {b.cta}", "", " ".join(b.hashtags), "",
            "## 版面建議", *[f"{i}. {x}" for i, x in enumerate(b.layout, 1)], "",
            "## 視覺方向", b.visual_direction, "", "## 顏色與字體", b.color_usage, "",
            "## 上線前檢查", *[f"- [ ] {x}" for x in b.checklist]]
    return "\n".join(out) + "\n"
