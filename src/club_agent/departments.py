"""社團部門與各部門顧問的角色設定。

本期以「行銷」為正式模組（另有數據診斷、宣傳企劃等專屬工具），
其餘部門以通用的「部門顧問」提供建議，標示為測試版，之後再逐一深化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .retriever import DEFAULT_KB_DIR, BM25Retriever, Chunk, split_markdown


@dataclass(frozen=True)
class Department:
    key: str
    name: str
    icon: str
    advisor_role: str = field(repr=False)
    focus: tuple[str, ...] = field(repr=False)
    example_questions: tuple[str, ...] = field(repr=False)
    beta: bool = True

    @property
    def label(self) -> str:
        return f"{self.icon} {self.name}{'（測試版）' if self.beta else ''}"


DEPARTMENTS: dict[str, Department] = {
    d.key: d
    for d in [
        Department(
            key="marketing",
            name="行銷",
            icon="📣",
            beta=False,
            advisor_role="資深校園社群行銷顧問",
            focus=("社群經營與數據解讀", "活動宣傳時程", "多平台文案", "品牌形象一致性"),
            example_questions=(
                "粉專觸及最近一直下降，下個月該怎麼調整發文策略？",
                "招生季快到了，要怎麼規劃兩週的宣傳？",
            ),
        ),
        Department(
            key="pr",
            name="公關",
            icon="🤝",
            advisor_role="社團公關與企業贊助顧問",
            focus=("企業贊助提案", "公關信與合作邀約", "跨社團與校外合作", "贊助回饋與露出"),
            example_questions=(
                "想找飲料店贊助成果展，提案信要怎麼寫？",
                "合作社團臨時退出聯展，要怎麼對外溝通？",
            ),
        ),
        Department(
            key="finance",
            name="財務",
            icon="💰",
            advisor_role="社團財務與預算健檢顧問",
            focus=("活動預算編列", "記帳與核銷流程", "社費與收支控管", "財務透明與交接"),
            example_questions=(
                "成果展預算 3 萬元，要怎麼分配比較合理？",
                "社費收支一直對不起來，記帳流程該怎麼改？",
            ),
        ),
        Department(
            key="events",
            name="活動",
            icon="🎪",
            advisor_role="校園活動企劃與執行顧問",
            focus=("活動企劃書", "流程與分工", "風險與應變", "參與者體驗與回饋"),
            example_questions=(
                "第一次辦迎新宿營，企劃書要包含哪些內容？",
                "活動當天人手不夠，事前要怎麼排班？",
            ),
        ),
        Department(
            key="venue",
            name="場地",
            icon="🏛️",
            advisor_role="場地租借與總務顧問",
            focus=("場地申請流程與時程", "場地選擇與動線", "器材與物資清點", "場地使用規範"),
            example_questions=(
                "期末成果展要借哪種場地？大概多久前要申請？",
                "社辦器材常常找不到，要怎麼管理借還？",
            ),
        ),
        Department(
            key="minutes",
            name="會議記錄",
            icon="📝",
            advisor_role="會議效率與文書顧問",
            focus=("會議議程設計", "會議紀錄格式", "決議與待辦追蹤", "交接文件整理"),
            example_questions=(
                "幹部會常常開很久沒結論，議程要怎麼設計？",
                "幫我整理一份會議紀錄的標準格式",
            ),
        ),
        Department(
            key="courses",
            name="課程",
            icon="📚",
            advisor_role="社課規劃與教學設計顧問",
            focus=("學期社課規劃", "講師邀請", "課程內容與教案", "出席率與學習回饋"),
            example_questions=(
                "社課出席率越來越低，要怎麼提升？",
                "幫我規劃一學期 12 堂的初學者社課",
            ),
        ),
    ]
}

DEPARTMENT_KB_DIR = DEFAULT_KB_DIR / "departments"
SHARED_KB_FILES = ("04_campus_promotion_guidelines.md",)


def get_department(key: str) -> Department:
    try:
        return DEPARTMENTS[key]
    except KeyError:
        raise ValueError(f"未知的部門：{key}（可用：{', '.join(DEPARTMENTS)}）") from None


def department_retriever(key: str, kb_dir: Path = DEFAULT_KB_DIR) -> BM25Retriever:
    """部門顧問的知識庫：行銷沿用行銷模組知識庫；其他部門用各自資料夾，再加上全社團共用的校園規範。"""
    get_department(key)
    if key == "marketing":
        return BM25Retriever.from_directory(kb_dir)
    chunks: list[Chunk] = []
    for path in sorted((kb_dir / "departments").glob(f"{key}*.md")):
        chunks.extend(split_markdown(path.name, path.read_text(encoding="utf-8")))
    for name in SHARED_KB_FILES:
        path = kb_dir / name
        if path.exists():
            chunks.extend(split_markdown(path.name, path.read_text(encoding="utf-8")))
    return BM25Retriever(chunks)
