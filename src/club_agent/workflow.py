"""多 Agent 協同工作流程。

情境 A：數據診斷 → DiagnosisReport
情境 B：（可選）數據診斷 → 文案策略 → 經營審查 →（未通過則退回修訂，最多 N 輪）→ CampaignResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .agents import CriticAgent, DiagnosticAgent, DraftingAgent
from .llm import LLM
from .metrics import MetricsSummary
from .retriever import BM25Retriever, Retriever
from .schemas import CampaignResult, ClubProfile, Critique, DiagnosisReport

ProgressFn = Callable[[str], None]


@dataclass
class MarketingWorkflow:
    llm: LLM
    retriever: Retriever = field(default_factory=BM25Retriever.from_directory)
    max_rounds: int = 3
    pass_score: float = 4.0
    on_progress: ProgressFn = lambda _msg: None

    def __post_init__(self) -> None:
        self.diagnostic = DiagnosticAgent(self.llm, self.retriever)
        self.drafting = DraftingAgent(self.llm, self.retriever)
        self.critic = CriticAgent(self.llm, pass_score=self.pass_score)

    def diagnose(self, club: ClubProfile, metrics: MetricsSummary, concern: str = "") -> DiagnosisReport:
        self.on_progress("數據診斷 Agent 分析中…")
        return self.diagnostic.run(club, metrics, concern)

    def campaign(
        self,
        club: ClubProfile,
        brief: str,
        diagnosis: DiagnosisReport | None = None,
    ) -> CampaignResult:
        critiques: list[Critique] = []
        plan = None
        for round_no in range(1, self.max_rounds + 1):
            self.on_progress(f"第 {round_no} 輪：文案與策略 Agent 撰寫中…")
            plan = self.drafting.run(
                club,
                brief,
                diagnosis,
                previous=plan,
                critique=critiques[-1] if critiques else None,
            )
            self.on_progress(f"第 {round_no} 輪：經營審查 Agent 評分中…")
            critique = self.critic.run(club, brief, plan)
            critiques.append(critique)
            self.on_progress(
                f"第 {round_no} 輪審查：平均 {critique.overall_score:.2f} 分，"
                f"{'通過' if critique.approved else '未通過，退回修訂'}"
            )
            if critique.approved:
                break
        assert plan is not None
        return CampaignResult(plan=plan, critiques=critiques, rounds=len(critiques), approved=critiques[-1].approved)
