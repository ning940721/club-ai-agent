from __future__ import annotations

from pathlib import Path

import pytest

from club_agent.schemas import (
    CampaignPlan,
    ClubProfile,
    Critique,
    DiagnosisReport,
    Finding,
    PostingSlot,
    RubricScore,
    SocialPost,
    TimelinePhase,
    TopicAllocation,
)

EXAMPLES = Path(__file__).parent.parent / "examples"


class FakeLLM:
    """依輸出型別回傳預先準備的結果，並記錄每次呼叫。"""

    def __init__(self, responses: dict[type, list]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, str, type]] = []

    def structured(self, system, user, output_type):
        self.calls.append((system, user, output_type))
        return self.responses[output_type].pop(0)


@pytest.fixture
def club() -> ClubProfile:
    return ClubProfile(name="測試社", category="學藝性", positioning="攝影", target_audience="大學生", monthly_budget_ntd=1000)


@pytest.fixture
def sample_csv() -> Path:
    return EXAMPLES / "sample_posts.csv"


def make_diagnosis() -> DiagnosisReport:
    return DiagnosisReport(
        summary="觸及下滑",
        bottlenecks=[Finding(title="公告型貼文過多", evidence="公告互動率 2.9%", impact="高")],
        audience_insights=["喜歡作品分享"],
        topic_allocation=[TopicAllocation(topic="作品分享", share_percent=40, rationale="互動最高")],
        best_posting_times=[PostingSlot(platform="Instagram", weekday="週四", time_range="21:00-22:00", rationale="觸及高")],
        priority_actions=["增加 Reels"],
        data_gaps=[],
    )


def make_plan(name: str = "企劃") -> CampaignPlan:
    return CampaignPlan(
        campaign_name=name,
        key_message="一起拍",
        target_audience="大一新生",
        timeline=[TimelinePhase(phase="預熱期", start_offset_days=-14, end_offset_days=-8, goal="曝光", tasks=["預告貼文"])],
        posts=[
            SocialPost(
                platform="Instagram",
                phase="預熱期",
                format="輪播",
                hook="你拍過雨天嗎？",
                body="內文",
                cta="點主頁連結報名",
                hashtags=["#攝影"],
                visual_suggestion="底片質感",
                suggested_publish_time="週四 21:00",
            )
        ],
        story_scripts=[],
        budget_notes="印刷 500 元",
        kpis=["報名 50 人"],
        references_used=["02_copywriting_templates.md"],
    )


def make_critique(scores: list[int]) -> Critique:
    return Critique(
        scores=[RubricScore(criterion=f"項目{i}", score=s, comment="") for i, s in enumerate(scores)],
        overall_score=5.0,  # 故意給錯，應由程式重算
        approved=True,  # 故意給錯，應由程式判定
        strengths=[],
        revision_requests=["CTA 加上截止日"],
    )
