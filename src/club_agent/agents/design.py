"""美宣 Agent：依設計需求與社團視覺規範寫設計說明與文案；依社團特色建議視覺規範初稿。"""

from __future__ import annotations

from ..llm import LLM
from ..schemas import BrandGuideDraft, ClubProfile, DesignBrief

BRIEF_PROMPT = """你是學生社團的美宣與文案顧問，把各部門的設計需求整理成美宣可以直接動手做的設計說明。

工作原則：
- 只使用需求中提供的資訊；沒有的時間、地點、報名方式等寫【待補：…】，不要捏造。
- 文案精簡：主標吸睛、內文條列必要資訊；依類型調整長度（IG 貼文可稍長，海報要一眼看懂）。
- 依社團視覺規範說明顏色與字體的用法；沒有規範時給一般建議並提醒建立規範。
- 尺寸與格式依需求的類型與尺寸。
- 全部使用繁體中文。"""

GUIDE_PROMPT = """你是學生社團的品牌與視覺顧問，替社團建議一份簡單好用的視覺規範初稿。

工作原則：
- 依社團定位與目標受眾決定風格；顏色 3–5 個並附色碼，主色和文字色要有足夠對比。
- 字體優先建議可免費商用的中文字體。
- 社團已有的設定要保留並在此基礎上補充，不要全部推翻。
- 規則要具體、學生美宣做得到。
- 全部使用繁體中文。"""


class DesignAssistant:
    def __init__(self, llm: LLM):
        self.llm = llm

    def brief(self, club: ClubProfile, guide_text: str, request_text: str, event_text: str = "", extra: str = "") -> DesignBrief:
        prompt = f"""<club>{club.name}：{club.positioning}；主要對象：{club.target_audience}</club>

<brand_guide>
{guide_text}
</brand_guide>

<request>
{request_text}
</request>

<event>
{event_text or "（沒有相關活動資料）"}
</event>

<extra_instructions>
{extra or "（無）"}
</extra_instructions>

請寫這份設計需求的設計說明與文案。"""
        return self.llm.structured(BRIEF_PROMPT, prompt, DesignBrief)

    def guide(self, club: ClubProfile, current_text: str, marketing_details: str = "", extra: str = "") -> BrandGuideDraft:
        prompt = f"""<club>{club.name}（{club.category}）：{club.positioning}；主要對象：{club.target_audience}</club>

<current_guide>
{current_text}
</current_guide>

<marketing_details>
{marketing_details or "（未填寫）"}
</marketing_details>

<extra_instructions>
{extra or "（無）"}
</extra_instructions>

請建議視覺規範。"""
        return self.llm.structured(GUIDE_PROMPT, prompt, BrandGuideDraft)
