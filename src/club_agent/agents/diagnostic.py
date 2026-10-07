"""數據診斷 Agent（Diagnostic Agent）。

輸入社團的社群數據統計與宣傳困擾，分析流量瓶頸與受眾偏好，點出宣傳盲點，
並給出「貼文主題分配」與「最佳發文時機」建議（實測情境 A）。
"""

from __future__ import annotations

from ..llm import LLM
from ..metrics import MetricsSummary
from ..retriever import Retriever, format_context
from ..schemas import ClubProfile, DiagnosisReport

SYSTEM_PROMPT = """你是一位資深的校園社團社群行銷顧問，專長是用數據診斷學生社團的社群經營問題。

工作原則：
- 所有結論都要引用下方提供的統計數字作為證據；統計已由程式計算，請直接使用，不要自行重算或捏造數字。
- 樣本數太少（例如某分組只有 1–2 篇）時，要明確說明結論的不確定性，並列入 data_gaps。
- 「資料完整度」列出的欄位是社團沒有記錄的資料（空白代表不知道，不是 0）：不要對缺少的資料下結論
  （例如沒有發文時間就不要建議最佳時段，改為建議開始記錄），並在 data_gaps 說明缺少什麼、下次怎麼補。
- 建議必須是學生社團在有限人力與預算下做得到的具體行動，避免空泛建議（如「提升內容品質」）。
- 可參考知識庫資料中的平台規律與基準值，但以該社團自身數據為主。
- 全部使用繁體中文。"""


class DiagnosticAgent:
    def __init__(self, llm: LLM, retriever: Retriever):
        self.llm = llm
        self.retriever = retriever

    def build_prompt(self, club: ClubProfile, metrics: MetricsSummary, concern: str) -> str:
        query = f"{concern} 觸及 互動率 演算法 發文時間 {club.target_audience}"
        context = format_context(self.retriever.search(query, k=4))
        return f"""<club_profile>
{club.model_dump_json(indent=2)}
</club_profile>

<metrics>
{metrics.to_prompt_text()}
</metrics>

<club_concern>
{concern or "（未提供，請就數據進行整體健檢）"}
</club_concern>

<knowledge_base>
{context}
</knowledge_base>

請診斷此社團的社群經營現況，找出流量瓶頸與宣傳盲點，並提出貼文主題分配與最佳發文時機建議。"""

    def run(self, club: ClubProfile, metrics: MetricsSummary, concern: str = "") -> DiagnosisReport:
        return self.llm.structured(SYSTEM_PROMPT, self.build_prompt(club, metrics, concern), DiagnosisReport)
