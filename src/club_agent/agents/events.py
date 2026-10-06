"""活動 Agent：產生活動企劃書、回饋表單題目與成果報告。"""

from __future__ import annotations

from ..departments import ClubSettings
from ..llm import LLM
from ..retriever import Retriever, format_context
from ..schemas import ClubProfile, EventProposal, EventReport, FeedbackForm

PROPOSAL_PROMPT = """你是學生社團的活動企劃顧問，替幹部寫出可以直接送幹部會或學校審核的活動企劃書。

工作原則：
- 依提供的活動資訊規劃；沒有提供的日期、金額、場地、人名以【待補：…】標示，不要捏造。
- 預算依一般學生活動行情估算並在 note 註明「估算」；總額盡量控制在提供的總預算內，若不足請在 note 說明需要的差額。
- 流程時間要連續，含報到、開場、主要活動、休息、結尾與場復。
- 籌備工作要具體（例：「向課外組申請學活中心 B1 場地」而不是「處理場地」），涵蓋場地、器材、宣傳、贊助、人力、保險與經費；
  department 只能使用提供的部門代號，days_before 是活動前幾天要完成。
- 參考知識庫的實務做法，但以這個社團的資訊為主。
- 全部使用繁體中文。"""

FEEDBACK_PROMPT = """你是學生社團的活動企劃顧問，替活動設計回饋表單。

工作原則：
- 8–12 題，填寫時間 3 分鐘內；先整體滿意度（線性刻度），再針對活動各環節，最後開放式建議與是否願意再參加。
- 題目要能幫助改進下次活動，避免重複或誘導性問題；不要詢問姓名、學號、電話等個資（除非是抽獎，且需標示選填）。
- 全部使用繁體中文。"""

REPORT_PROMPT = """你是學生社團的活動企劃顧問，替幹部撰寫活動成果報告（可用於學校補助核銷、社團交接）。

工作原則：
- 只根據提供的資料撰寫；數字（人數、金額）照提供的寫，沒有的資料寫【待補】。
- 目標達成情形要逐項對照企劃書的目標與實際結果。
- 檢討要具體、可執行，交接重點寫給下一屆辦同樣活動的人看。
- 全部使用繁體中文。"""


def _departments(settings: ClubSettings) -> str:
    return "\n".join(f"- {k}：{settings.name(k)}" for k in settings.enabled_keys())


class EventPlanner:
    def __init__(self, llm: LLM, retriever: Retriever | None = None):
        self.llm = llm
        self.retriever = retriever

    def propose(self, club: ClubProfile, settings: ClubSettings, facts: str, extra: str = "") -> EventProposal:
        knowledge = format_context(self.retriever.search(facts, k=4)) if self.retriever else ""
        prompt = f"""<club>{club.name}：{club.positioning}；主要對象：{club.target_audience}</club>

<departments>
{_departments(settings)}
</departments>

<event_department_details>
{settings.details("events") or "（未填寫）"}
</event_department_details>

<event>
{facts}
</event>

<extra_instructions>
{extra or "（無）"}
</extra_instructions>

<knowledge>
{knowledge or "（無）"}
</knowledge>

請撰寫這個活動的企劃書。"""
        return self.llm.structured(PROPOSAL_PROMPT, prompt, EventProposal)

    def feedback_form(self, club: ClubProfile, facts: str, content: str = "", extra: str = "") -> FeedbackForm:
        prompt = f"""<club>{club.name}</club>

<event>
{facts}
</event>

<event_content>
{content or "（沒有企劃書內容）"}
</event_content>

<extra_instructions>
{extra or "（無）"}
</extra_instructions>

請設計這個活動的回饋表單。"""
        return self.llm.structured(FEEDBACK_PROMPT, prompt, FeedbackForm)

    def report(self, club: ClubProfile, facts: str, proposal_text: str, results_text: str) -> EventReport:
        prompt = f"""<club>{club.name}</club>

<event>
{facts}
</event>

<proposal>
{proposal_text or "（沒有企劃書）"}
</proposal>

<actual_results>
{results_text}
</actual_results>

請撰寫成果報告。"""
        return self.llm.structured(REPORT_PROMPT, prompt, EventReport)
