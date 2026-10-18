from club_agent.store import LocalClubStore
from club_agent.usage import add_usage, monthly_usage


def test_usage_counts_per_club_and_month(tmp_path, club):
    store = LocalClubStore(tmp_path)
    c1 = store.create_club("club-one", "secret123", club)
    c2 = store.create_club("club-two", "secret123", club)
    assert monthly_usage(store, c1, "2026-10") == 0
    assert add_usage(store, c1, "2026-10") == 1
    assert add_usage(store, c1, "2026-10") == 2
    assert monthly_usage(store, c1, "2026-11") == 0
    assert monthly_usage(store, c2, "2026-10") == 0
