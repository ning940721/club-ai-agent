"""Agent 之間傳遞的結構化資料格式。

所有 LLM 輸出都以 Pydantic 模型約束（Structured Outputs），
確保「數據診斷 → 文案策略 → 經營審查」三層 Agent 之間的交接穩定可解析。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["Instagram", "Facebook", "Dcard", "Threads", "IG限時動態"]


# ---------------------------------------------------------------------------
# 輸入：社團基本資料與社群數據
# ---------------------------------------------------------------------------


class ClubProfile(BaseModel):
    """社團定位資料，讓產出擺脫套版感、貼合社團特色。"""

    name: str
    category: str = Field(description="社團類型，如：學術性、康樂性、服務性、系學會")
    positioning: str = Field(description="社團定位與特色")
    target_audience: str = Field(description="主要目標受眾")
    brand_voice: str = Field(default="親切、有活力", description="品牌語氣")
    platforms: list[str] = Field(default_factory=lambda: ["Instagram", "Facebook"])
    monthly_budget_ntd: int = Field(default=0, description="每月可用行銷預算（新台幣）")
    notes: str = ""


class PostRecord(BaseModel):
    """單篇貼文的成效數據（可由 IG/FB 洞察報告匯出後整理為 CSV）。"""

    date: str = Field(description="發文日期 YYYY-MM-DD")
    time: str = Field(default="", description="發文時間 HH:MM")
    platform: str
    post_type: str = Field(description="貼文形式，如：圖文、輪播、Reels、限動")
    topic: str = Field(description="貼文主題分類，如：活動宣傳、幹部介紹、社課花絮")
    reach: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    followers: int = Field(default=0, description="發文當下粉絲數")
    caption: str = ""


# ---------------------------------------------------------------------------
# 數據診斷 Agent 輸出
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    title: str
    evidence: str = Field(description="支持此發現的數據證據（需引用具體數字）")
    impact: Literal["高", "中", "低"]


class TopicAllocation(BaseModel):
    topic: str
    share_percent: int = Field(description="建議在總貼文中所占百分比")
    rationale: str


class PostingSlot(BaseModel):
    platform: str
    weekday: str
    time_range: str
    rationale: str


class DiagnosisReport(BaseModel):
    summary: str = Field(description="一段話總結目前社群經營狀態")
    bottlenecks: list[Finding] = Field(description="流量瓶頸與宣傳盲點")
    audience_insights: list[str] = Field(description="受眾偏好洞察")
    topic_allocation: list[TopicAllocation] = Field(description="建議的貼文主題分配")
    best_posting_times: list[PostingSlot] = Field(description="最佳發文時機建議")
    priority_actions: list[str] = Field(description="依優先順序排列的具體改善行動")
    data_gaps: list[str] = Field(description="數據不足、無法下結論之處（避免 AI 幻覺）")


# ---------------------------------------------------------------------------
# 文案與策略 Agent 輸出
# ---------------------------------------------------------------------------


class TimelinePhase(BaseModel):
    phase: str = Field(description="階段名稱，如：預熱期、報名期、倒數期、活動後")
    start_offset_days: int = Field(description="相對活動日的起始天數（負數表示活動前）")
    end_offset_days: int
    goal: str
    tasks: list[str]
    owner: str = Field(default="行銷部", description="負責部門或角色")


class SocialPost(BaseModel):
    platform: str
    phase: str = Field(description="對應的宣傳階段")
    format: str = Field(description="貼文形式，如：輪播圖文、Reels、限動、Dcard 長文")
    hook: str = Field(description="開頭吸睛句")
    body: str = Field(description="完整貼文內文")
    cta: str = Field(description="明確的行動呼籲")
    hashtags: list[str]
    visual_suggestion: str = Field(description="視覺／素材建議")
    suggested_publish_time: str


class StoryScript(BaseModel):
    title: str
    frames: list[str] = Field(description="每一格限時動態的畫面與文字")
    interaction: str = Field(description="互動設計，如：投票、問答、倒數貼紙")


class CampaignPlan(BaseModel):
    campaign_name: str
    key_message: str
    target_audience: str
    timeline: list[TimelinePhase] = Field(description="多階段宣傳時程（行銷甘特圖）")
    posts: list[SocialPost] = Field(description="多平台客製化貼文")
    story_scripts: list[StoryScript]
    budget_notes: str = Field(description="預算運用說明，須在社團預算內")
    kpis: list[str] = Field(description="可量化的成效指標")
    references_used: list[str] = Field(description="參考了哪些知識庫文件（檔名）")


# ---------------------------------------------------------------------------
# 經營審查 Agent 輸出
# ---------------------------------------------------------------------------


class RubricScore(BaseModel):
    criterion: str
    score: int = Field(description="1–5 分")
    comment: str


class Critique(BaseModel):
    scores: list[RubricScore]
    overall_score: float = Field(description="各項平均分數（1–5）")
    approved: bool
    strengths: list[str]
    revision_requests: list[str] = Field(description="具體、可執行的修改要求；通過時可為空")


# ---------------------------------------------------------------------------
# 工作流程最終結果
# ---------------------------------------------------------------------------


class CampaignResult(BaseModel):
    plan: CampaignPlan
    critiques: list[Critique]
    rounds: int
    approved: bool
