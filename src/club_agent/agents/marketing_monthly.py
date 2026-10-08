"""行銷月報 Agent：比較本月與上月的社群表現，整理成果與問題，規劃下個月的內容與目標。"""

from __future__ import annotations

from ..llm import LLM
from ..schemas import ClubProfile, MarketingMonthlyReview

SYSTEM_PROMPT = """你是學生社團的社群行銷顧問，每個月替行銷幹部寫一份社群月報。

工作原則：
- 數字已由程式計算，直接引用，不要自行重算或捏造；結論要附上數字證據（例如「平均互動率 4.8% → 6.1%」）。
- 本月或某分組貼文數很少（1–2 篇）時，說明結論不確定。
- 「資料完整度」列出的是沒有記錄的資料（空白代表不知道，不是 0）：不要對缺少的資料下結論，改在 data_to_collect 建議補記。
- 沒有上月資料時，只分析本月，不要假設成長或衰退。
- 下月規劃要是學生社團人力做得到的，並考量社團接下來的活動。
- 全部使用繁體中文。"""


class MonthlyReviewer:
    def __init__(self, llm: LLM):
        self.llm = llm

    def run(self, club: ClubProfile, comparison_text: str, trend_text: str, upcoming: str = "", concern: str = "") -> MarketingMonthlyReview:
        prompt = f"""<club>{club.name}：{club.positioning}；主要對象：{club.target_audience}</club>

<monthly_data>
{comparison_text}
</monthly_data>

<history_trend>
{trend_text or "（只有一個月的資料）"}
</history_trend>

<upcoming_events>
{upcoming or "（行事曆沒有接下來的活動）"}
</upcoming_events>

<concern>
{concern or "（無）"}
</concern>

請撰寫本月社群月報。"""
        return self.llm.structured(SYSTEM_PROMPT, prompt, MarketingMonthlyReview)
