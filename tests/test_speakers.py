from datetime import date

from club_agent.agents import LetterWriter
from club_agent.departments import ClubSettings
from club_agent.events import club_events
from club_agent.schemas import Letter
from club_agent.speakers import Talk, TimeSlot, confirm, list_talks, needs_follow_up, save_talk, talks_markdown
from club_agent.store import LocalClubStore

from conftest import FakeLLM


def make_talk(**kw) -> Talk:
    data = dict(speaker="王小明", affiliation="自由攝影師", contact="ming@example.com", topic="手機街拍", fee=2000, owner="小美")
    data.update(kw)
    return Talk(**data)


def test_confirm_sorting_and_follow_up(tmp_path, club):
    store = LocalClubStore(tmp_path)
    cid = store.create_club("talk-club", "secret123", club)
    a = make_talk(stage="洽談中", follow_up="2026-10-05",
                  candidates=[TimeSlot(date="2026-11-05"), TimeSlot(date="2026-11-12", start="18:30", end="20:30")])
    b = confirm(make_talk(speaker="陳老師", topic="底片沖洗"), TimeSlot(date="2026-10-30"))
    save_talk(store, cid, a)
    save_talk(store, cid, b)
    talks = list_talks(store, cid)
    assert [t.speaker for t in talks] == ["陳老師", "王小明"]  # 已確認的排前面
    assert b.stage == "已確認" and b.follow_up == ""
    assert [t.speaker for t in needs_follow_up(talks, date(2026, 10, 6))] == ["王小明"]
    assert TimeSlot(date="2026-11-12", start="18:30", end="20:30").label() == "2026-11-12（四） 18:30–20:30"

    events = {e.title: e for e in club_events(store, cid, ClubSettings.default())}
    talk_event = events["講座：底片沖洗（陳老師）"]
    assert (talk_event.date, talk_event.time, talk_event.department) == ("2026-10-30", "19:00", "speakers")
    assert events["追蹤講者：王小明（洽談中）"].kind == "截止"


def test_facts_mark_unknowns_and_summary():
    t = make_talk(candidates=[TimeSlot(date="2026-11-05")])
    facts = t.facts()
    assert "地點：未定" in facts and "講師費：2,000 元" in facts and "候選時間：2026-11-05（四） 19:00–21:00" in facts
    done = confirm(make_talk(speaker="陳老師", topic="底片", location="社辦"), TimeSlot(date="2026-10-30"))
    md = talks_markdown("測試社", [done, t], date(2026, 8, 1), date(2027, 1, 31))
    assert "## 已確認的講座（1 場）" in md and "陳老師（自由攝影師）" in md and "講師費合計：2,000 元" in md
    assert "## 洽談中（1 場）" in md and "| 王小明 | 手機街拍 | 待聯絡 |" in md


def test_letter_writer_prompt(club):
    llm = FakeLLM({Letter: [Letter(subject="邀請", body="您好", short_text="短")]})
    LetterWriter(llm).run(club, "講者部", "邀請信", "第一次邀請", make_talk().facts(), "語氣輕鬆")
    prompt = llm.calls[0][1]
    assert "<letter_type>邀請信：第一次邀請</letter_type>" in prompt and "講者：王小明（自由攝影師）" in prompt
    assert "語氣輕鬆" in prompt and "測試社 講者部" in prompt
