from club_agent.metrics import engagement_rate, load_posts_csv, summarize
from club_agent.schemas import PostRecord


def test_engagement_rate():
    p = PostRecord(date="2026-03-02", platform="Instagram", post_type="輪播", topic="x", reach=200, likes=10, comments=4, shares=3, saves=3)
    assert engagement_rate(p) == 0.1
    assert engagement_rate(p.model_copy(update={"reach": 0})) is None  # 不知道，不是 0%


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


def test_parse_big5_csv_from_excel():
    from club_agent.metrics import decode_csv_bytes, parse_posts_csv

    text = "date,platform,post_type,topic,reach,likes\n2026-09-01,Instagram,輪播,活動宣傳,100,10\n,,,,,\n"
    posts = parse_posts_csv(decode_csv_bytes(text.encode("cp950")))
    assert len(posts) == 1 and posts[0].topic == "活動宣傳"


def test_blank_fields_mean_unknown_not_zero():
    from club_agent.metrics import parse_posts_csv

    text = (
        "日期,時間,形式,主題,觸及人數,按讚,留言,分享,粉絲數\n"
        "2026-09-01,21:00,輪播,活動,1000,80,10,,1200\n"
        "2026/9/8,,Reels,社課,,50,5,,\n"
        "2026-09-15 下午 1:30,,輪播,活動,500,40,0,,\n"
        ",,輪播,活動,500,40,0,,\n"
    )
    posts = parse_posts_csv(text, default_platform="Instagram")
    assert len(posts) == 3 and posts[0].platform == "Instagram"
    assert posts[1].reach is None and posts[1].shares is None and posts[2].time == "13:30"
    assert engagement_rate(posts[1]) is None  # 沒有觸及人數 → 不計算
    s = summarize(posts)
    assert s.avg_reach == 750 and round(s.avg_engagement_rate, 3) == round((0.09 + 0.08) / 2, 3)
    assert (s.follower_start, s.follower_end) == (1200, 1200)
    assert [g.key for g in s.by_hour] == ["深夜 21-06", "下午 12-17"]  # 沒有時間的不列入
    text = s.to_prompt_text()
    assert "[資料完整度]" in text and "分享：全部沒有資料" in text and "觸及人數：2/3 篇有資料" in text
    assert "互動率計算包含：按讚、留言" in text


def test_column_mapping_and_formats():
    from club_agent.metrics import guess_mapping, parse_datetime, parse_number, parse_time

    meta = ["Post ID", "Publish time", "Post type", "Reach", "Likes", "Comments", "Shares", "Saves", "Description"]
    assert guess_mapping(meta) == {"date": "Publish time", "post_type": "Post type", "reach": "Reach", "likes": "Likes",
                                   "comments": "Comments", "shares": "Shares", "saves": "Saves", "caption": "Description"}
    zh = ["發文日期", "發文時間", "平台", "貼文形式", "主題分類", "觸及人數", "按讚數", "留言數", "轉發數", "收藏數", "追蹤者人數"]
    m = guess_mapping(zh)
    assert (m["date"], m["time"], m["shares"], m["followers"], m["post_type"]) == ("發文日期", "發文時間", "轉發數", "追蹤者人數", "貼文形式")
    assert parse_datetime("03/02/2026 13:05") == ("2026-03-02", "13:05")
    assert parse_datetime("2026年3月2日") == ("2026-03-02", None)
    assert parse_time("3:20 PM") == "15:20" and parse_time("上午 12:10") == "00:10" and parse_time("不知道") is None
    assert parse_number("1,234") == 1234 and parse_number("-") is None and parse_number("") is None and parse_number("850 人") == 850
