"""財務分析 Agent：根據月報或學期報表的數字，整理財務狀況、提醒風險並給改善建議。"""

from __future__ import annotations

from ..llm import LLM
from ..schemas import ClubProfile, FinanceReview

SYSTEM_PROMPT = """你是學生社團的財務顧問，負責解讀社團的收支報表並給財務與社長建議。

工作原則：
- 只根據提供的數字分析，不要捏造金額；計算時寫出依據（例如「餐飲已用 4,200／預算 5,000，執行率 84%」）。
- 優先指出：超支或即將超支的類別、待審核或待撥款累積太多、收入來源過度集中、期末餘額不足以支應已核准款項。
- 建議要具體、學生社團做得到，例如調整預算類別、提前申請補助、統一撥款日、活動前先編預算。
- 全部使用繁體中文。"""


class FinanceAnalyst:
    def __init__(self, llm: LLM):
        self.llm = llm

    def run(self, club: ClubProfile, report_text: str, finance_details: str = "") -> FinanceReview:
        prompt = f"""<club>{club.name}：{club.positioning}</club>

<finance_rules>
{finance_details or "（未填寫財務部門細節）"}
</finance_rules>

<report>
{report_text}
</report>

請分析這份報表。"""
        return self.llm.structured(SYSTEM_PROMPT, prompt, FinanceReview)
