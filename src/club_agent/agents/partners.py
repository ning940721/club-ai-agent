"""公關 Agent：依社團與活動建議可以接洽的贊助／合作對象類型。

只建議「對象類型與搜尋關鍵字」，不提供具體店名或聯絡方式，避免過時或錯誤的資訊；
由幹部搜尋、確認後再加入合作對象名單。
"""

from __future__ import annotations

from ..llm import LLM
from ..schemas import ClubProfile, SponsorIdeas

SYSTEM_PROMPT = """你是學生社團的公關與贊助顧問，協助幹部找出值得接洽的贊助或合作對象。

工作原則：
- 只建議對象「類型」，不要寫出具體店名、品牌名稱、人名或聯絡方式（資訊可能過時或錯誤）。
- 以學生社團實際談得成的對象為主：學校周邊店家、與社團主題相關的在地商家、系友、其他社團、校內單位；大型企業放在後面並說明門檻。
- 請求與回饋要對等且具體：請求寫出合理規模，回饋寫出可量化的露出（貼文次數、攤位、背板 logo、活動人數）。
- 搜尋關鍵字要包含地區（依提供的學校或地點），方便直接在 Google 地圖或 IG 搜尋。
- 參考「已經在名單上的對象」，避免重複建議同類型。
- 全部使用繁體中文。"""


class SponsorAdvisor:
    def __init__(self, llm: LLM):
        self.llm = llm

    def run(self, club: ClubProfile, event_text: str, area: str, existing: str, pr_details: str = "", extra: str = "") -> SponsorIdeas:
        prompt = f"""<club>{club.name}（{club.category}）：{club.positioning}；主要對象：{club.target_audience}</club>

<area>{area or "未提供（請在關鍵字中以【學校名稱】代替）"}</area>

<event>
{event_text or "（沒有指定活動，給社團長期合作的建議）"}
</event>

<pr_department_details>
{pr_details or "（未填寫）"}
</pr_department_details>

<existing_partners>
{existing or "（名單是空的）"}
</existing_partners>

<extra_instructions>
{extra or "（無）"}
</extra_instructions>

請建議可以接洽的對象類型。"""
        return self.llm.structured(SYSTEM_PROMPT, prompt, SponsorIdeas)
