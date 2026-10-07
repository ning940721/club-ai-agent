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

    date: str = Field(description="發文日期 YYYY-MM-DD（唯一必填）")
    time: str = Field(default="", description="發文時間 HH:MM；不知道時空白")
    platform: str = ""
    post_type: str = Field(default="", description="貼文形式，如：圖文、輪播、Reels、限動")
    topic: str = Field(default="", description="貼文主題分類，如：活動宣傳、幹部介紹、社課花絮")
    # 數字欄位：None 代表「不知道」，和 0 不同，計算平均時會排除
    reach: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    followers: int | None = Field(default=None, description="發文當下粉絲數")
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


# ---------------------------------------------------------------------------
# 部門顧問輸出
# ---------------------------------------------------------------------------


class ActionStep(BaseModel):
    step: str = Field(description="步驟名稱")
    detail: str = Field(description="具體做法")
    owner: str = Field(description="建議負責的部門或角色")
    timing: str = Field(description="建議完成時間，如：活動前 3 週、本週內")


class Deliverable(BaseModel):
    title: str = Field(description="文件名稱，如：贊助提案信模板、預算表欄位、會議紀錄格式")
    content: str = Field(description="可直接複製使用的完整內容（Markdown）")


class Coordination(BaseModel):
    department: str = Field(description="需要協作的部門")
    what: str = Field(description="需要對方配合或提供的事項")


class Advice(BaseModel):
    summary: str = Field(description="一段話回答使用者的問題與核心建議")
    steps: list[ActionStep] = Field(description="依先後順序排列的行動步驟")
    deliverables: list[Deliverable] = Field(description="可直接使用的文件或模板；不需要時可為空")
    coordination: list[Coordination] = Field(description="需要和其他部門協作的事項；不需要時可為空")
    risks: list[str] = Field(description="需要注意的風險或常見錯誤")
    info_needed: list[str] = Field(description="還需要使用者補充、才能給出更精準建議的資訊")


# ---------------------------------------------------------------------------
# 會議記錄：重點彙整與問答
# ---------------------------------------------------------------------------


class ActionItem(BaseModel):
    task: str = Field(description="要做的事")
    owner: str = Field(description="負責人；記錄中沒有寫明時填空字串")
    department: str = Field(description="負責部門的代號，必須是提供的部門清單中的代號；無法判斷時填 president")
    due: str = Field(description="期限 YYYY-MM-DD；記錄中沒有寫明時填空字串")


class KeyDate(BaseModel):
    event: str = Field(description="事件，如：下次幹部會、成果展、報名截止")
    date: str = Field(description="日期 YYYY-MM-DD；只知道月日時依記錄日期推算年份")
    time: str = Field(description="時間 HH:MM；不知道時填空字串")
    location: str = Field(description="地點；不知道時填空字串")


AGENDA_RESULTS = ("已決議", "已討論、未決議", "未討論")


class AgendaCheck(BaseModel):
    topic: str = Field(description="議程上的議題，照原議程填寫")
    result: Literal["已決議", "已討論、未決議", "未討論"]
    note: str = Field(description="決議內容或目前討論到哪裡；未討論時填空字串")


class MeetingSummary(BaseModel):
    title: str = Field(description="會議或對話的簡短標題")
    summary: str = Field(description="3–5 句重點摘要")
    decisions: list[str] = Field(description="已做成的決議")
    action_items: list[ActionItem] = Field(description="待辦事項")
    key_dates: list[KeyDate] = Field(description="提到的重要日期，包含下次開會時間")
    open_questions: list[str] = Field(description="尚未決定、需要後續討論的事項")
    agenda_review: list[AgendaCheck] = Field(
        default_factory=list, description="對照 <agenda> 的每個議題逐一判斷結果；沒有提供議程時為空陣列"
    )

    def unresolved_agenda(self) -> list[AgendaCheck]:
        return [c for c in self.agenda_review if c.result != "已決議"]


class SourceRef(BaseModel):
    title: str = Field(description="來源會議記錄的標題")
    date: str = Field(description="來源的日期")
    excerpt: str = Field(description="支持答案的原文片段（直接引用）")


class MeetingAnswer(BaseModel):
    found: bool = Field(description="記錄中是否找得到答案")
    answer: str = Field(description="直接回答問題；找不到時說明記錄中沒有提到")
    sources: list[SourceRef] = Field(description="答案依據的原文；找不到時為空")


# ---------------------------------------------------------------------------
# 社長：進度彙整與會議議程
# ---------------------------------------------------------------------------


class DepartmentStatus(BaseModel):
    department: str = Field(description="部門名稱")
    doing: list[str] = Field(description="目前正在進行的事")
    progress: str = Field(description="一句話描述整體進度")
    blockers: list[str] = Field(description="卡關、逾期或需要協助的事項；沒有時為空")


class AgendaItem(BaseModel):
    topic: str = Field(description="議題")
    department: str = Field(description="負責報告或主持的部門")
    kind: Literal["報告", "討論", "決議"]
    minutes: int = Field(description="建議討論分鐘數")
    goal: str = Field(description="這個議題要得到什麼結果")


class ProgressBrief(BaseModel):
    overview: str = Field(description="全社團目前狀態的總結（3–5 句）")
    departments: list[DepartmentStatus]
    agenda: list[AgendaItem] = Field(description="下次會議建議議程，依討論順序排列")
    decisions_needed: list[str] = Field(description="需要社長或幹部會做決定的事項")
    reminders: list[str] = Field(description="近期重要日期與提醒")


# ---------------------------------------------------------------------------
# 財務
# ---------------------------------------------------------------------------


class FinanceReview(BaseModel):
    summary: str = Field(description="這段期間財務狀況的總結（2–4 句）")
    warnings: list[str] = Field(description="需要注意的地方，例如超支、待撥款累積、收入不足；沒有時為空")
    suggestions: list[str] = Field(description="具體可執行的改善建議（3–5 點）")


# ---------------------------------------------------------------------------
# 信件與通知（講者、公關共用）
# ---------------------------------------------------------------------------


class Letter(BaseModel):
    subject: str = Field(description="信件主旨；社員通知則為貼文標題")
    body: str = Field(description="完整內文，可直接寄出或貼上；未知資訊以【待補：…】標示")
    short_text: str = Field(description="LINE／簡訊用的短版（150 字以內）")


# ---------------------------------------------------------------------------
# 活動專案
# ---------------------------------------------------------------------------


class RundownItem(BaseModel):
    start: str = Field(description="開始時間 HH:MM")
    end: str = Field(description="結束時間 HH:MM")
    item: str = Field(description="流程項目")
    owner: str = Field(description="負責的角色或組別，例如：主持人、場控組")
    note: str = Field(description="注意事項；沒有時填空字串")


class BudgetLine(BaseModel):
    item: str = Field(description="支出項目")
    category: str = Field(description="類別：必須是 <budget_categories> 中的其中一個")
    amount: int = Field(description="預估金額（元）；不確定時依一般行情估算，並在 note 註明「估算」")
    note: str = Field(description="說明；沒有時填空字串")


class PrepTask(BaseModel):
    task: str = Field(description="籌備工作，要具體可執行")
    department: str = Field(description="負責部門代號，必須是提供的部門清單中的代號")
    days_before: int = Field(description="活動前幾天要完成（活動當天為 0）")


class RiskItem(BaseModel):
    risk: str
    response: str = Field(description="預防與應變方式")


class EventProposal(BaseModel):
    purpose: str = Field(description="活動緣起與目的（2–3 句）")
    goals: list[str] = Field(description="具體、可衡量的目標")
    audience: str = Field(description="目標對象與預計人數")
    content: list[str] = Field(description="活動內容規劃，依進行順序")
    rundown: list[RundownItem] = Field(description="活動當天流程草稿，時間要連續")
    budget: list[BudgetLine] = Field(description="預算規劃；總額盡量不超過提供的預算")
    staffing: list[str] = Field(description="人力配置：各組名稱、人數與職責")
    promotion: list[str] = Field(description="宣傳規劃與時程")
    prep_tasks: list[PrepTask] = Field(description="籌備工作清單，涵蓋場地、器材、宣傳、贊助、人力、保險等")
    risks: list[RiskItem] = Field(description="風險與應變")
    kpis: list[str] = Field(description="成效指標")


class FeedbackQuestion(BaseModel):
    question: str
    type: Literal["單選", "複選", "線性刻度", "簡答", "段落"]
    options: list[str] = Field(description="單選／複選的選項；線性刻度填兩端說明（例：非常不滿意、非常滿意）；簡答與段落為空")
    required: bool


class FeedbackForm(BaseModel):
    title: str
    intro: str = Field(description="表單開頭說明（感謝參加、填寫時間約幾分鐘）")
    questions: list[FeedbackQuestion] = Field(description="8–12 題，先整體滿意度，再各環節，最後開放建議")


class EventReport(BaseModel):
    summary: str = Field(description="活動成果摘要（3–5 句）")
    results: list[str] = Field(description="目標達成情形，逐項對照目標與實際數字")
    highlights: list[str] = Field(description="亮點與成功之處")
    budget_review: str = Field(description="預算執行說明：預算與實際支出的差異與原因")
    feedback_summary: str = Field(description="參加者回饋重點")
    improvements: list[str] = Field(description="檢討與下次改進建議，要具體")
    handover: list[str] = Field(description="給下一屆辦同樣活動的交接重點")


# ---------------------------------------------------------------------------
# 公關：贊助對象建議
# ---------------------------------------------------------------------------


class SponsorIdea(BaseModel):
    target_type: str = Field(description="對象類型，例如：學校周邊早午餐店、相機器材行、系友創業的品牌；不要寫具體店名")
    why: str = Field(description="為什麼適合：受眾重疊或品牌調性")
    ask: str = Field(description="建議請求的內容與合理規模，例如：物資贊助 30 份飲料、現金 2,000–5,000 元")
    offer: str = Field(description="我們可以提供的回饋，要具體可量化")
    search_keywords: list[str] = Field(description="2–3 組可以在 Google 地圖或 IG 搜尋的關鍵字，含地區")


class SponsorIdeas(BaseModel):
    ideas: list[SponsorIdea] = Field(description="5–8 個建議，依成功機率由高到低")
    tips: list[str] = Field(description="這次接洽的注意事項（3–5 點）")
