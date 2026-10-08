from club_agent.post_history import compare_month, list_history, months, previous_month, save_posts
from club_agent.report import monthly_report_markdown
from club_agent.schemas import ContentPlanItem, MarketingMonthlyReview, PostRecord
from club_agent.store import LocalClubStore


def post(day, reach=None, likes=None, followers=None, caption="", **kw) -> PostRecord:
    return PostRecord(date=day, time="20:00", platform="Instagram", post_type="輪播", topic="活動", reach=reach,
                      likes=likes, followers=followers, caption=caption, **kw)


def test_save_merges_and_keeps_known_values(tmp_path, club):
    store = LocalClubStore(tmp_path)
    cid = store.create_club("mk-club", "secret123", club)
    assert save_posts(store, cid, [post("2026-09-01", 500, 40, 1000, "迎新"), post("2026-09-08", 600, 30, caption="社課")]) == (2, 0)
    # 再上傳同一篇：觸及更新、粉絲數空白 → 保留舊值；加上新月份的貼文
    assert save_posts(store, cid, [post("2026-09-01", 800, None, None, "迎新"), post("2026-10-02", 900, 90, 1100, "成果展")]) == (1, 1)
    history = list_history(store, cid)
    first = history[0]
    assert (first.reach, first.likes, first.followers) == (800, 40, 1000)
    assert months(history) == ["2026-10", "2026-09"] and previous_month("2026-01") == "2025-12"


def test_compare_month_rows_and_report():
    history = [post("2026-09-01", 500, 50, 1000), post("2026-09-20", 500, 30, 1020), post("2026-10-03", 1000, 120, 1100)]
    c = compare_month(history, "2026-10")
    rows = {name: (now, prev, diff) for name, now, prev, diff in c.rows()}
    assert rows["貼文數"] == ("1", "2", "-1 篇")
    assert rows["平均觸及"] == ("1,000", "500", "+100.0%")
    assert rows["平均互動率"] == ("12.00%", "8.00%", "+4.00 個百分點")
    assert rows["月底粉絲數"] == ("1,100", "1,020", "+80")
    assert "[本月與上月比較：2026-10 vs 2026-09]" in c.to_prompt_text()
    assert compare_month(history, "2026-09").before is None

    review = MarketingMonthlyReview(summary="互動率上升", wins=["成果展貼文 12%"], issues=["貼文數減少"],
                                    next_month_plan=[ContentPlanItem(topic="作品分享", format="輪播", timing="週日 21:00", purpose="維持互動")],
                                    kpi_targets=["互動率 ≥ 10%"], data_to_collect=["記錄發文時間"])
    md = monthly_report_markdown("測試社", "2026-10", c.rows(), review)
    assert "| 平均互動率 | 12.00% | 8.00% | +4.00 個百分點 |" in md and "| 作品分享 | 輪播 | 週日 21:00 | 維持互動 |" in md
    assert "## 下個月請補記的資料" in md
