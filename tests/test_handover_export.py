import io
import zipfile
from datetime import date

import pandas as pd

from club_agent.departments import ClubSettings
from club_agent.finance import FinanceSettings, save_settings
from club_agent.handover_export import build_handover_zip, safe_name
from club_agent.meetings import MeetingDoc, save_meeting
from club_agent.members import Member, save_member
from club_agent.projects import EventProject, save_project
from club_agent.schemas import EventReport
from club_agent.store import LocalClubStore, Record
from club_agent.tasks import Task, save_task

from test_meetings import make_summary


def _read(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def test_handover_zip_contents_and_privacy(tmp_path, club):
    store = LocalClubStore(tmp_path)
    cid = store.create_club("pack-club", "secret123", club)
    settings = ClubSettings.default()
    save_task(store, cid, Task(title="寄贊助信", department="pr", due="2026-10-20"))
    save_meeting(store, cid, MeetingDoc(title="第 5 次幹部會", date="2026-10-03", text="原文", summary=make_summary()))
    store.add_record(cid, Record(department="marketing", kind="diagnosis", title="社群數據診斷", summary="", markdown="# 診斷\n\n內容"))
    report = EventReport(summary="順利", results=["180 人"], highlights=[], budget_review="—", feedback_summary="好評",
                         improvements=[], handover=[])
    save_project(store, cid, EventProject(name="成果展", date="2026-12-20", budget=5000, report=report))
    save_member(store, cid, Member(name="王小明", contact="0912-345-678"))
    save_settings(store, cid, FinanceSettings())

    data, files = build_handover_zip(store, cid, club, settings, manuals={"pr": "# 公關交接手冊\n\n內容"}, today=date(2026, 10, 9))
    root = f"{safe_name(club.name)}_交接資料_20261009"
    rel = {f.removeprefix(root + "/") for f in files}
    assert {"00_資料包說明.docx", "01_全社團/待辦與進度.xlsx", "01_全社團/行事曆.ics", "02_會議記錄/2026-10-03_第 5 次幹部會_重點.docx",
            "02_會議記錄/原文/2026-10-03_第 5 次幹部會.txt", "03_各部門/行銷/分享的成果/" + Record(department="x", kind="x", title="x",
            summary="", markdown="").created_at[:10] + "_社群數據診斷.docx", "03_各部門/公關/交接手冊.docx",
            "04_活動專案/2026-12-20_成果展/成果報告.docx", "10_人資/社員名單.xlsx"} <= rel
    assert not any(f.startswith("11_財務") for f in rel)
    z = _read(data)
    roster = pd.read_excel(io.BytesIO(z.read(f"{root}/10_人資/社員名單.xlsx")))
    assert "聯絡方式" not in roster.columns  # 預設不含個資

    data, files = build_handover_zip(store, cid, club, settings, include_finance=True, include_contacts=True, today=date(2026, 10, 9))
    rel = {f.removeprefix(root + "/") for f in files}
    assert any(f.startswith("11_財務/學期財務報表") for f in rel) and "11_財務/報帳與財務規範.docx" in rel
    roster = pd.read_excel(io.BytesIO(_read(data).read(f"{root}/10_人資/社員名單.xlsx")))
    assert roster.loc[0, "聯絡方式"] == "0912-345-678"


def test_safe_name():
    assert safe_name('成果展: "海報"/A3?') == "成果展_ _海報_A3"
