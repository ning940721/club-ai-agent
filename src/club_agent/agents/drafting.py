"""文案與策略 Agent（Drafting Agent）。

根據診斷結果與 RAG 檢索到的範本，生成多階段宣傳時程（行銷甘特圖）、
多平台客製化貼文與限時動態腳本（實測情境 B）。收到審查意見時會據以修訂。
"""

from __future__ import annotations

from ..llm import LLM
from ..retriever import Retriever, format_context
from ..schemas import CampaignPlan, ClubProfile, Critique, DiagnosisReport

SYSTEM_PROMPT = """你是一位擅長校園社群的行銷企劃與文案寫手，負責為學生社團產出可以直接執行的宣傳企劃。

工作原則：
- 內容要貼合社團的定位、品牌語氣與目標受眾，避免任何社團都能套用的套版文案。
- 每篇貼文都要包含：吸睛開頭、完整活動資訊（時間、地點、費用、報名方式；未知的資訊用【待補：…】標示，絕不捏造）、一個明確的 CTA。
- 依平台特性調整寫法：IG 重視視覺與收藏、FB 適合正式公告與活動頁、Dcard 避免硬廣告改用經驗分享口吻、Threads 口語互動。
- 時程要可執行，並標示負責部門；預算運用不得超過社團提供的預算。
- 參考知識庫中的範本與時程，並在 references_used 列出實際參考的檔名。
- 若提供了數據診斷結果，策略需回應其中指出的瓶頸。
- 全部使用繁體中文。"""


class DraftingAgent:
    def __init__(self, llm: LLM, retriever: Retriever):
        self.llm = llm
        self.retriever = retriever

    def build_prompt(
        self,
        club: ClubProfile,
        brief: str,
        diagnosis: DiagnosisReport | None = None,
        previous: CampaignPlan | None = None,
        critique: Critique | None = None,
    ) -> str:
        query = f"{brief} 宣傳時程 文案 範本 CTA {' '.join(club.platforms)}"
        context = format_context(self.retriever.search(query, k=6))
        parts = [
            f"<club_profile>\n{club.model_dump_json(indent=2)}\n</club_profile>",
            f"<campaign_brief>\n{brief}\n</campaign_brief>",
        ]
        if diagnosis:
            parts.append(f"<diagnosis>\n{diagnosis.model_dump_json(indent=2)}\n</diagnosis>")
        parts.append(f"<knowledge_base>\n{context}\n</knowledge_base>")
        if previous and critique:
            parts.append(f"<previous_plan>\n{previous.model_dump_json(indent=2)}\n</previous_plan>")
            parts.append(f"<critique>\n{critique.model_dump_json(indent=2)}\n</critique>")
            parts.append("上一版企劃未通過審查。請逐條回應 critique 中的 revision_requests，保留原本做得好的部分，輸出完整的修訂版企劃。")
        else:
            parts.append("請產出完整的多階段宣傳企劃，包含時程、各平台貼文與限時動態腳本。")
        return "\n\n".join(parts)

    def run(
        self,
        club: ClubProfile,
        brief: str,
        diagnosis: DiagnosisReport | None = None,
        previous: CampaignPlan | None = None,
        critique: Critique | None = None,
    ) -> CampaignPlan:
        prompt = self.build_prompt(club, brief, diagnosis, previous, critique)
        return self.llm.structured(SYSTEM_PROMPT, prompt, CampaignPlan)
