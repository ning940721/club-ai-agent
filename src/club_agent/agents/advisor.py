"""部門顧問 Agent（Department Advisor）。

使用者選擇自己的部門並輸入問題，Agent 扮演該部門的資深顧問，
結合社團資料、部門知識庫與其他部門的近期動態，產出可直接執行的建議與文件模板。
"""

from __future__ import annotations

from ..departments import ClubSettings, Department
from ..llm import LLM
from ..retriever import Retriever, format_context
from ..schemas import Advice, ClubProfile

SYSTEM_PROMPT = """你是一位{role}，正在協助一個學生社團的「{name}」部門。
你的專長包括：{focus}。

工作原則：
- 針對使用者的問題給出學生社團在有限人力、時間與預算下做得到的具體建議，避免空泛的原則。
- 步驟要能直接照著做，並標示負責的部門或角色與建議時程。
- 需要文件時（信件、表格欄位、議程、企劃架構等），直接在 deliverables 提供可複製使用的完整內容。
- 不知道的社團細節（日期、金額、場地、人名等）以【待補：…】標示，絕不捏造。
- 涉及學校規定（場地、核銷、宣傳張貼等）時，提醒使用者向校內負責單位確認最新規定。
- 參考「其他部門近期動態」，若和其他部門有關聯或需要協作，寫在 coordination。
- 全部使用繁體中文。"""


class DepartmentAdvisor:
    def __init__(self, llm: LLM, retriever: Retriever):
        self.llm = llm
        self.retriever = retriever

    def system_prompt(self, dept: Department, settings: ClubSettings | None = None) -> str:
        name = settings.name(dept.key) if settings else dept.name
        return SYSTEM_PROMPT.format(role=dept.advisor_role, name=name, focus="、".join(dept.focus))

    def build_prompt(
        self,
        club: ClubProfile,
        dept: Department,
        question: str,
        club_activity: str = "",
        settings: ClubSettings | None = None,
        dept_tasks: str = "",
    ) -> str:
        context = format_context(self.retriever.search(f"{dept.name} {question}", k=4))
        details = settings.details(dept.key) if settings else ""
        return f"""<club_profile>
{club.model_dump_json(indent=2)}
</club_profile>

<department_details>
{details or "（社團尚未填寫這個部門的細節）"}
</department_details>

<department_tasks>
{dept_tasks or "（沒有未完成的任務）"}
</department_tasks>

<other_departments_recent_activity>
{club_activity or "（目前沒有其他部門的紀錄）"}
</other_departments_recent_activity>

<knowledge_base>
{context}
</knowledge_base>

<question>
{question}
</question>

請以部門顧問的角色回答這個問題，並遵守部門細節中的規定。"""

    def run(
        self,
        club: ClubProfile,
        dept: Department,
        question: str,
        club_activity: str = "",
        settings: ClubSettings | None = None,
        dept_tasks: str = "",
    ) -> Advice:
        prompt = self.build_prompt(club, dept, question, club_activity, settings, dept_tasks)
        return self.llm.structured(self.system_prompt(dept, settings), prompt, Advice)
