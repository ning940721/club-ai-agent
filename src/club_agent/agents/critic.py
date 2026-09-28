"""經營審查 Agent（Critic Agent）。

扮演「資深行銷總監」，依評分表檢查文案吸引力、CTA 明確度、品牌一致性與預算可行性。
是否通過由程式依分數門檻判定，不完全交給模型自行決定，確保審查標準一致。
"""

from __future__ import annotations

from statistics import mean

from ..llm import LLM
from ..schemas import CampaignPlan, ClubProfile, Critique

RUBRIC: list[tuple[str, str]] = [
    ("內容吸引力", "開頭能否在 3 秒內抓住校園受眾注意力，是否具備擴散與分享動機"),
    ("資訊完備度", "時間、地點、費用、報名方式等活動資訊是否完整；未知資訊是否誠實標示待補而非捏造"),
    ("CTA 明確度", "每篇貼文是否有單一、具體、含期限的行動呼籲"),
    ("客製化與貼合度", "是否貼合該社團的定位、語氣與受眾，而非套版內容；是否依平台特性調整"),
    ("時程可執行性", "宣傳階段安排是否合理、分工清楚，避開考試週等不利時段"),
    ("品牌與預算一致性", "是否符合社團品牌形象，預算運用是否在社團預算內"),
]

SYSTEM_PROMPT = """你是一位嚴格但具建設性的資深行銷總監，負責審查學生社團的宣傳企劃。

請依下列評分表逐項給 1–5 分（5 = 可直接發布，3 = 堪用但有明顯改進空間，1 = 需重寫）：
{rubric}

審查原則：
- 評語要指出具體是哪一篇貼文或哪一個階段有問題。
- revision_requests 必須是撰稿者可以直接照做的修改指示。
- 發現捏造的日期、地點、價格或數據時，「資訊完備度」最高只能給 2 分。
- 全部使用繁體中文。"""


def _rubric_text() -> str:
    return "\n".join(f"- {name}：{desc}" for name, desc in RUBRIC)


class CriticAgent:
    def __init__(self, llm: LLM, pass_score: float = 4.0, min_item_score: int = 3):
        self.llm = llm
        self.pass_score = pass_score
        self.min_item_score = min_item_score

    def build_prompt(self, club: ClubProfile, brief: str, plan: CampaignPlan) -> str:
        return f"""<club_profile>
{club.model_dump_json(indent=2)}
</club_profile>

<campaign_brief>
{brief}
</campaign_brief>

<campaign_plan>
{plan.model_dump_json(indent=2)}
</campaign_plan>

請依評分表審查這份宣傳企劃。"""

    def run(self, club: ClubProfile, brief: str, plan: CampaignPlan) -> Critique:
        system = SYSTEM_PROMPT.format(rubric=_rubric_text())
        critique = self.llm.structured(system, self.build_prompt(club, brief, plan), Critique)
        return self.apply_threshold(critique)

    def apply_threshold(self, critique: Critique) -> Critique:
        """以程式重新計算平均分並判定是否通過。"""
        if not critique.scores:
            return critique.model_copy(update={"approved": False})
        avg = round(mean(s.score for s in critique.scores), 2)
        approved = avg >= self.pass_score and all(s.score >= self.min_item_score for s in critique.scores)
        return critique.model_copy(update={"overall_score": avg, "approved": approved})
