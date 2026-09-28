from club_agent.metrics import engagement_rate, load_posts_csv, summarize
from club_agent.schemas import PostRecord


def test_engagement_rate():
    p = PostRecord(date="2026-03-02", platform="Instagram", post_type="輪播", topic="x", reach=200, likes=10, comments=4, shares=3, saves=3)
    assert engagement_rate(p) == 0.1
    assert engagement_rate(p.model_copy(update={"reach": 0})) == 0.0


def test_summarize_sample(sample_csv):
    posts = load_posts_csv(sample_csv)
    s = summarize(posts)
    assert s.total_posts == len(posts)
    assert [m.key for m in s.by_month] == sorted(m.key for m in s.by_month)
    assert s.by_topic[0].avg_engagement_rate >= s.by_topic[-1].avg_engagement_rate
    text = s.to_prompt_text()
    for section in ("月度趨勢", "依主題", "依貼文形式", "依發文時段", "互動率最高的貼文"):
        assert section in text


def test_weekday_and_hour_buckets():
    posts = [
        PostRecord(date="2026-09-28", time="21:30", platform="IG", post_type="Reels", topic="a", reach=100, likes=10),
        PostRecord(date="2026-09-29", time="08:00", platform="IG", post_type="Reels", topic="a", reach=100, likes=5),
    ]
    s = summarize(posts)
    assert {g.key for g in s.by_weekday} == {"週一", "週二"}
    assert {g.key for g in s.by_hour} == {"深夜 21-06", "早上 06-12"}
    assert s.reach_trend_percent is None
