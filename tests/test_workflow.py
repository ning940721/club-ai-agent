import pytest

from club_agent.agents import CriticAgent
from club_agent.metrics import load_posts_csv, summarize
from club_agent.report import campaign_markdown, diagnosis_markdown
from club_agent.retriever import BM25Retriever
from club_agent.schemas import CampaignPlan, Critique, DiagnosisReport
from club_agent.workflow import MarketingWorkflow

from conftest import FakeLLM, make_critique, make_diagnosis, make_plan


def test_critic_threshold_recomputed():
    critic = CriticAgent(llm=None, pass_score=4.0, min_item_score=3)
    c = critic.apply_threshold(make_critique([5, 5, 5, 2]))
    assert c.overall_score == 4.25 and c.approved is False  # 單項低於 3 分不通過
    assert critic.apply_threshold(make_critique([4, 4, 4, 5])).approved is True
    assert critic.apply_threshold(make_critique([3, 4, 4, 4])).approved is False  # 平均 3.75


def test_diagnose_prompt_contains_metrics_and_knowledge(club, sample_csv):
    llm = FakeLLM({DiagnosisReport: [make_diagnosis()]})
    wf = MarketingWorkflow(llm=llm, retriever=BM25Retriever.from_directory())
    report = wf.diagnose(club, summarize(load_posts_csv(sample_csv)), "觸及下降")
    assert report.summary == "觸及下滑"
    _, user, _ = llm.calls[0]
    assert "<metrics>" in user and "平均互動率" in user
    assert "<knowledge_base>" in user and "【" in user
    assert "觸及下降" in user


def test_campaign_revises_until_approved(club):
    llm = FakeLLM(
        {
            CampaignPlan: [make_plan("v1"), make_plan("v2")],
            Critique: [make_critique([3, 3, 4, 4]), make_critique([5, 4, 4, 5])],
        }
    )
    wf = MarketingWorkflow(llm=llm, retriever=BM25Retriever.from_directory(), max_rounds=3)
    result = wf.campaign(club, "期末成果展", make_diagnosis())
    assert result.rounds == 2 and result.approved
    assert result.plan.campaign_name == "v2"
    second_draft_prompt = llm.calls[2][1]
    assert "<previous_plan>" in second_draft_prompt and "CTA 加上截止日" in second_draft_prompt
    assert "<diagnosis>" in second_draft_prompt


def test_campaign_stops_at_max_rounds(club):
    llm = FakeLLM({CampaignPlan: [make_plan(), make_plan()], Critique: [make_critique([2] * 4), make_critique([2] * 4)]})
    result = MarketingWorkflow(llm=llm, retriever=BM25Retriever.from_directory(), max_rounds=2).campaign(club, "社課")
    assert result.rounds == 2 and not result.approved


def test_reports_render(club):
    assert "流量瓶頸" in diagnosis_markdown(club.name, make_diagnosis())
    from club_agent.schemas import CampaignResult

    md = campaign_markdown(CampaignResult(plan=make_plan(), critiques=[make_critique([5, 5, 5, 5])], rounds=1, approved=True))
    assert "D-14 ~ D-8" in md and "點主頁連結報名" in md
