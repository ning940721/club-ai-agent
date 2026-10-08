from datetime import date

from club_agent.departments import ClubSettings
from club_agent.design import BrandColor, BrandGuide, DesignRequest, brief_markdown, guide_markdown, list_requests, save_request
from club_agent.events import club_events
from club_agent.schemas import DesignBrief
from club_agent.store import LocalClubStore


def test_requests_order_overdue_and_calendar(tmp_path, club):
    store = LocalClubStore(tmp_path)
    cid = store.create_club("design-club", "secret123", club)
    save_request(store, cid, DesignRequest(title="迎新海報", department="events", due="2026-10-20"))
    save_request(store, cid, DesignRequest(title="社課貼文", department="courses", due="2026-10-05", status="製作中"))
    save_request(store, cid, DesignRequest(title="舊的", department="pr", due="2026-09-01", status="已完成"))
    items = list_requests(store, cid)
    assert [r.title for r in items] == ["社課貼文", "迎新海報", "舊的"]
    assert items[0].is_overdue(date(2026, 10, 9)) and not items[2].is_overdue(date(2026, 10, 9))
    titles = [e.title for e in club_events(store, cid, ClubSettings.default())]
    assert "設計截止：迎新海報（待接單）" in titles and not any("舊的" in t for t in titles)


def test_guide_and_brief_documents():
    guide = BrandGuide(colors=[BrandColor(name="主色", hex="#2D4A6B", usage="標題")], heading_font="思源黑體", tone="親切")
    assert "- 主色 #2D4A6B：標題" in guide.to_text() and BrandGuide().is_empty()
    assert "| 主色 | #2D4A6B | 標題 |" in guide_markdown("測試社", guide)
    r = DesignRequest(title="成果展海報", department="events", kind="海報", size="A3", due="2026-12-01",
                      brief=DesignBrief(headline="看見城市", subheadline="期末成果展", body_copy="12/20 學活", cta="掃碼報名",
                                        hashtags=["#攝影"], layout=["上方主視覺"], visual_direction="底片感", color_usage="主色標題",
                                        checklist=["日期星期正確"]))
    md = brief_markdown(r, {"events": "活動"}.get)
    assert "**提出：** 活動" in md and "**主標：** 看見城市" in md and "- [ ] 日期星期正確" in md
