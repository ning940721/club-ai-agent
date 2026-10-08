from datetime import date

from club_agent.departments import ClubSettings
from club_agent.events import club_events
from club_agent.store import LocalClubStore
from club_agent.venue import (
    Booking,
    Equipment,
    Loan,
    apply_deadline,
    available,
    bookings_markdown,
    list_bookings,
    list_loans,
    save_booking,
    save_equipment,
    save_loan,
)


def test_booking_deadlines_and_warnings():
    assert apply_deadline(date(2026, 11, 20), 14) == date(2026, 11, 6)
    b = Booking(venue="演藝廳", date="2026-11-20", apply_by="2026-11-06")
    assert b.apply_warning(date(2026, 10, 1)) == ""
    assert b.apply_warning(date(2026, 11, 3)) == "申請期限剩 3 天"
    assert b.apply_warning(date(2026, 11, 6)) == "今天是申請期限"
    assert b.apply_warning(date(2026, 11, 8)) == "已超過申請期限 2 天"
    assert b.model_copy(update={"status": "已申請"}).apply_warning(date(2026, 11, 8)) == ""
    md = bookings_markdown("測試社", [b, Booking(venue="教室", date="2026-11-01", status="取消")])
    assert "| 2026-11-20 |  | 演藝廳 | — | 2026-11-06 | 待申請 | — |" in md and "教室" not in md


def test_equipment_loans_and_calendar(tmp_path, club):
    store = LocalClubStore(tmp_path)
    cid = store.create_club("venue-club", "secret123", club)
    cam = Equipment(name="相機", quantity=3)
    save_equipment(store, cid, cam)
    save_loan(store, cid, Loan(equipment_id=cam.id, equipment_name="相機", borrower="小明", quantity=2, due="2026-10-05"))
    save_loan(store, cid, Loan(equipment_id=cam.id, equipment_name="相機", borrower="小華", quantity=1, due="2026-09-01", returned="2026-09-01"))
    loans = list_loans(store, cid)
    assert available(cam, loans) == 1 and loans[0].is_overdue(date(2026, 10, 9)) and not loans[1].is_overdue(date(2026, 10, 9))
    save_booking(store, cid, Booking(venue="演藝廳", purpose="社員大會", date="2026-11-20", start="18:00", end="21:00", apply_by="2026-11-06"))
    assert list_bookings(store, cid)[0].venue == "演藝廳"
    titles = [e.title for e in club_events(store, cid, ClubSettings.default())]
    assert "場地：演藝廳（社員大會）" in titles and "申請場地截止：演藝廳（2026-11-20 使用）" in titles
    assert "器材歸還：相機 × 2（小明）" in titles and not any("小華" in t for t in titles)
