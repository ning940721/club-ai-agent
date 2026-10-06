from datetime import date

from club_agent.agents import SponsorAdvisor
from club_agent.departments import ClubSettings
from club_agent.events import club_events
from club_agent.partners import Partner, list_partners, needs_follow_up, save_partner, sponsorship_markdown
from club_agent.schemas import SponsorIdea, SponsorIdeas
from club_agent.store import LocalClubStore

from conftest import FakeLLM


def test_partner_order_follow_up_and_calendar(tmp_path, club):
    store = LocalClubStore(tmp_path)
    cid = store.create_club("pr-club", "secret123", club)
    save_partner(store, cid, Partner(name="早午餐店", stage="待聯絡"))
    save_partner(store, cid, Partner(name="相機行", stage="洽談中", follow_up="2026-10-05", owner="小美"))
    save_partner(store, cid, Partner(name="飲料店", stage="合作中", amount=3000, event="期末成果展"))
    partners = list_partners(store, cid)
    assert [p.name for p in partners] == ["相機行", "早午餐店", "飲料店"]
    assert [p.name for p in needs_follow_up(partners, date(2026, 10, 6))] == ["相機行"]
    titles = [e.title for e in club_events(store, cid, ClubSettings.default())]
    assert "追蹤合作：相機行（洽談中）" in titles


def test_sponsorship_summary():
    partners = [
        Partner(name="飲料店", stage="合作中", amount=3000, in_kind="50 杯飲料", offer="IG 貼文 2 篇", event="成果展"),
        Partner(name="書店", stage="已結束", amount=1000, event="成果展"),
        Partner(name="相機行", stage="洽談中", follow_up="2026-10-20", owner="小美"),
        Partner(name="婉拒的店", stage="婉拒"),
    ]
    md = sponsorship_markdown("測試社", partners)
    assert "## 已談成（2 個，現金合計 4,000 元）" in md and "### 成果展（現金 4,000 元）" in md
    assert "| 飲料店 | 廠商／店家 | 3,000 | 50 杯飲料 | IG 貼文 2 篇 | 合作中 |" in md
    assert "| 相機行 | 廠商／店家 | — | 洽談中 | 2026-10-20 | 小美 |" in md and "婉拒的店" not in md


def test_sponsor_advisor_prompt(club):
    ideas = SponsorIdeas(ideas=[SponsorIdea(target_type="學校周邊飲料店", why="受眾重疊", ask="50 杯飲料", offer="IG 貼文",
                                            search_keywords=["公館 飲料店"])], tips=["提早一個月聯絡"])
    llm = FakeLLM({SponsorIdeas: [ideas]})
    SponsorAdvisor(llm).run(club, "活動名稱：成果展", "台大公館", "- 飲料店（廠商／店家，合作中）", "回饋可提供攤位")
    system, prompt, _ = llm.calls[0]
    assert "不要寫出具體店名" in system
    assert "<area>台大公館</area>" in prompt and "- 飲料店（廠商／店家，合作中）" in prompt and "回饋可提供攤位" in prompt
