"""社團部門、各部門顧問角色，以及每個社團的部門設定。

每個社團可以選擇啟用哪些部門、自訂部門名稱，並填寫「部門細節」（例如報帳規定、
固定開會時間），AI 會依這些細節微調建議。行銷為正式模組，其餘部門標示為測試版。

「功能模組」（FEATURES）和部門是分開的：每個部門預設負責哪些模組由 Department.features 決定，
社團可以在設定中改變分工（例如公關兼講者、活動兼總務），也可以新增系統沒有的自訂部門並指定它負責的模組。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from .retriever import DEFAULT_KB_DIR, BM25Retriever, Chunk, split_markdown

# 各部門可用的專屬功能（網頁分頁）
FEATURE_PRESIDENT = "president_overview"
FEATURE_MEETINGS = "meetings"
FEATURE_MARKETING = "marketing_tools"
FEATURE_PR = "pr_tools"  # 合作對象名單、贊助對象建議、對外信件
FEATURE_EVENTS = "event_projects"  # 活動專案：企劃書、籌備清單、細流、回饋表單、成果報告
FEATURE_SPEAKERS = "speaker_tools"  # 講座邀約、時間敲定、信件與宣傳通知
FEATURE_FINANCE = "finance_tools"  # 財務管理（以財務密碼上鎖，財務與社長使用）
FEATURE_DESIGN = "design_tools"  # 美宣：設計需求單、視覺規範（併入行銷）
FEATURE_COURSES = "course_tools"  # 社課：學期課表、出席與回饋

# 社團可以分配給部門的功能模組（設定頁的選項，依顯示順序）
FEATURES: dict[str, tuple[str, str]] = {
    FEATURE_PRESIDENT: ("社團總覽", "各部門進度、會議時間表與議程"),
    FEATURE_MEETINGS: ("會議記錄", "上傳會議記錄、整理重點、記錄問答"),
    FEATURE_MARKETING: ("社群數據與月報", "貼文數據診斷、月報與趨勢"),
    FEATURE_DESIGN: ("美宣設計", "處理各部門的設計需求、視覺規範、AI 設計說明與文案"),
    FEATURE_EVENTS: ("活動專案", "企劃書、籌備清單、細流、回饋表單、成果報告"),
    FEATURE_PR: ("合作與贊助", "找贊助對象、合作對象、合作信件"),
    FEATURE_SPEAKERS: ("講座管理", "講者邀約、時間敲定、信件與通知"),
    FEATURE_COURSES: ("社課", "AI 規劃學期課表、出席與回饋"),
    FEATURE_FINANCE: ("財務管理", "報帳審核、帳簿、預算、報表（財務密碼上鎖）"),
}
LEGACY_NAMES = {"design": "美宣"}  # 已併入行銷的舊部門，舊紀錄仍顯示原名稱


@dataclass(frozen=True)
class Department:
    key: str
    name: str
    advisor_role: str = field(repr=False)
    focus: tuple[str, ...] = field(repr=False)
    example_questions: tuple[str, ...] = field(repr=False)
    details_hint: str = field(default="", repr=False)
    features: tuple[str, ...] = field(default=(), repr=False)
    beta: bool = True

    @property
    def label(self) -> str:
        return f"{self.name}{'（測試版）' if self.beta else ''}"


DEPARTMENTS: dict[str, Department] = {
    d.key: d
    for d in [
        Department(
            key="president",
            name="社長",
            advisor_role="社團經營與領導顧問",
            focus=("各部門進度掌握", "會議議程規劃", "組織分工與決策", "社團年度規劃"),
            example_questions=("幹部之間分工不清楚，要怎麼重新安排？", "這學期的社團目標要怎麼訂？"),
            details_hint="例：幹部會每兩週一次；重大決策需幹部會過半同意；本學期目標是招到 40 位新社員",
            features=(FEATURE_PRESIDENT, FEATURE_FINANCE),
        ),
        Department(
            key="marketing",
            name="行銷",
            beta=False,
            advisor_role="資深校園社群行銷顧問",
            focus=("社群經營與數據解讀", "活動宣傳時程", "多平台文案", "品牌形象與視覺設計", "海報與貼文設計需求"),
            example_questions=("粉專觸及最近一直下降，下個月該怎麼調整發文策略？", "成果展海報要怎麼寫設計需求？"),
            details_hint="例：主要經營 IG，每週發 2 篇；主視覺色為深藍與米白、字體用思源黑體；海報需提前兩週完成",
            features=(FEATURE_MARKETING, FEATURE_DESIGN),
        ),
        Department(
            key="pr",
            name="公關",
            advisor_role="社團公關與企業贊助顧問",
            focus=("企業贊助提案", "公關信與合作邀約", "跨社團與校外合作", "贊助回饋與露出"),
            example_questions=("想找飲料店贊助成果展，提案信要怎麼寫？", "合作社團臨時退出聯展，要怎麼對外溝通？"),
            details_hint="例：常合作對象為校園周邊餐飲；贊助回饋可提供 IG 貼文與攤位；對外信件需副本給社長",
            features=(FEATURE_PR,),
        ),
        Department(
            key="finance",
            name="財務",
            advisor_role="社團財務與預算健檢顧問",
            focus=("活動預算編列", "記帳與核銷流程", "社費與收支控管", "財務透明與交接"),
            example_questions=("成果展預算 3 萬元，要怎麼分配比較合理？", "社費收支一直對不起來，記帳流程該怎麼改？"),
            details_hint="例：報帳需附發票正本與活動名稱；500 元以上需社長核准；每月 5 號統一撥款",
            features=(FEATURE_FINANCE,),
        ),
        Department(
            key="events",
            name="活動",
            advisor_role="校園活動企劃與執行顧問",
            focus=("活動企劃書", "流程與分工", "風險與應變", "參與者體驗與回饋"),
            example_questions=("第一次辦迎新宿營，企劃書要包含哪些內容？", "活動當天人手不夠，事前要怎麼排班？"),
            details_hint="例：每學期固定辦迎新、期中聯誼、期末成果展；活動企劃需在一個月前送幹部會",
            features=(FEATURE_EVENTS,),
        ),
        Department(
            key="minutes",
            name="會議記錄",
            advisor_role="會議效率與文書顧問",
            focus=("會議議程設計", "會議紀錄格式", "決議與待辦追蹤", "交接文件整理"),
            example_questions=("幹部會常常開很久沒結論，議程要怎麼設計？", "幫我整理一份會議紀錄的標準格式"),
            details_hint="例：幹部會固定週三晚上 7 點；主要溝通在 LINE 幹部群組；會議記錄存放在雲端硬碟",
            features=(FEATURE_MEETINGS,),
        ),
        Department(
            key="courses",
            name="課程",
            advisor_role="社課規劃與教學設計顧問",
            focus=("學期社課規劃", "講師邀請", "課程內容與教案", "出席率與學習回饋"),
            example_questions=("社課出席率越來越低，要怎麼提升？", "幫我規劃一學期 12 堂的初學者社課"),
            details_hint="例：社課每週四晚上；講師費每堂 1,500 元；學員多為零基礎",
            features=(FEATURE_COURSES,),
        ),
        Department(
            key="speakers",
            name="講者",
            advisor_role="講座企劃與講者邀約顧問",
            focus=("尋找與邀請講者", "講座主題與時間敲定", "講者聯繫與接待", "講座宣傳與社員通知"),
            example_questions=("想找業界攝影師來分享，要去哪裡找、怎麼開口邀請？", "講者臨時說不能來，要怎麼應變？"),
            details_hint="例：每學期辦 3 場講座；講師費 2,000 元＋交通費實報；講座固定在週四晚上，地點為社辦或學活中心",
            features=(FEATURE_SPEAKERS,),
        ),
        Department(
            key="venue",
            name="總務（場地、器材）",
            advisor_role="場地租借與總務顧問",
            focus=("場地申請流程與時程", "場地選擇與動線", "器材與物資清點", "場地使用規範"),
            example_questions=("期末成果展要借哪種場地？大概多久前要申請？", "社辦器材常常找不到，要怎麼管理借還？"),
            details_hint="例：社辦在學生活動中心 3 樓；常借場地為小福樓會議室；器材有相機 3 台、腳架 5 支",
        ),
        Department(
            key="members",
            name="人資／社員",
            advisor_role="社團人資與組織發展顧問",
            focus=("招生與面試流程", "社員參與與留任", "幹部培訓", "交接手冊"),
            example_questions=("新社員參加幾次就不來了，要怎麼提升留任？", "幹部交接要準備哪些文件？"),
            details_hint="例：社員約 60 人；幹部任期一年，每年 6 月交接；社費一學期 500 元",
        ),
    ]
}

# 新社團預設啟用的部門；其他部門可在設定中開啟
DEFAULT_ENABLED = ("president", "marketing", "pr", "finance", "events", "minutes")

DEPARTMENT_KB_DIR = DEFAULT_KB_DIR / "departments"
SHARED_KB_FILES = ("04_campus_promotion_guidelines.md",)


class DepartmentConfig(BaseModel):
    enabled: bool = False
    display_name: str = Field(default="", description="社團自訂的部門名稱，空白時使用預設名稱")
    details: str = Field(default="", description="部門細節，AI 會參考")
    features: list[str] | None = Field(default=None, description="這個部門負責的功能模組；None 表示使用部門預設")
    custom: bool = Field(default=False, description="社團自訂的部門（系統沒有的部門）")


CUSTOM_PREFIX = "custom_"


class MeetingDefaults(BaseModel):
    """幹部會議的固定時間與時長，社長頁面會自動帶入並記住上次的設定。"""

    start: str = Field(default="19:00", description="開始時間 HH:MM")
    minutes: int = Field(default=90, ge=10, le=480, description="會議時長（分鐘）")
    location: str = ""


class ClubSettings(BaseModel):
    departments: dict[str, DepartmentConfig] = Field(default_factory=dict)
    meeting: MeetingDefaults = Field(default_factory=MeetingDefaults)

    @classmethod
    def default(cls, enabled: tuple[str, ...] | list[str] = DEFAULT_ENABLED) -> ClubSettings:
        return cls(departments={k: DepartmentConfig(enabled=k in enabled) for k in DEPARTMENTS})

    def config(self, key: str) -> DepartmentConfig:
        return self.departments.get(key) or DepartmentConfig()

    def custom_keys(self) -> list[str]:
        return [k for k, c in self.departments.items() if c.custom]

    def all_keys(self) -> list[str]:
        """系統部門（依 DEPARTMENTS 順序）＋自訂部門（依新增順序）。"""
        return [*DEPARTMENTS, *self.custom_keys()]

    def enabled_keys(self) -> list[str]:
        """依 DEPARTMENTS 的順序列出已啟用的部門，自訂部門排在後面。"""
        return [k for k in self.all_keys() if self.config(k).enabled]

    def features(self, key: str) -> tuple[str, ...]:
        """這個部門負責的功能模組（社團自訂的分工優先，否則用部門預設）。"""
        cfg = self.config(key)
        if cfg.features is not None:
            return tuple(f for f in FEATURES if f in cfg.features)
        return DEPARTMENTS[key].features if key in DEPARTMENTS else ()

    def department(self, key: str) -> Department:
        """部門定義；自訂部門依名稱與負責的模組產生一個通用的顧問角色。"""
        if key in DEPARTMENTS:
            return DEPARTMENTS[key]
        name = self.name(key)
        focus = tuple(FEATURES[f][0] for f in self.features(key)) or ("部門營運與分工",)
        return Department(
            key=key, name=name, advisor_role=f"學生社團「{name}」的營運顧問", focus=(*focus, "工作規劃與交接"),
            example_questions=(f"{name}這學期的工作要怎麼規劃？", f"{name}的工作要怎麼分配給組員？"),
            details_hint="例：這個部門負責的工作、固定時程、和其他部門怎麼分工",
            features=self.features(key),
        )

    def with_custom(self, name: str, features: list[str], details: str = "") -> tuple[ClubSettings, str]:
        """新增一個自訂部門；回傳 (新設定, 部門代號)。"""
        import uuid

        key = f"{CUSTOM_PREFIX}{uuid.uuid4().hex[:6]}"
        config = DepartmentConfig(enabled=True, display_name=name.strip(), details=details, features=features, custom=True)
        return self.model_copy(update={"departments": {**self.departments, key: config}}), key

    def name(self, key: str) -> str:
        cfg = self.config(key)
        if cfg.display_name.strip():
            return cfg.display_name.strip()
        if key in DEPARTMENTS:
            return DEPARTMENTS[key].name
        return LEGACY_NAMES.get(key, key)

    def label(self, key: str) -> str:
        """選單與列表顯示用的部門名稱。測試版標示只出現在部門頁面內，不放在選單中。"""
        return self.name(key)

    def details(self, key: str) -> str:
        return self.config(key).details.strip()

    def all_details_text(self) -> str:
        """給 AI 參考的全社團部門設定摘要。"""
        lines = []
        for k in self.enabled_keys():
            detail = self.details(k)
            lines.append(f"- {self.name(k)}：{detail or '（未填寫細節）'}")
        return "\n".join(lines)


def get_department(key: str) -> Department:
    try:
        return DEPARTMENTS[key]
    except KeyError:
        raise ValueError(f"未知的部門：{key}（可用：{', '.join(DEPARTMENTS)}）") from None


def department_retriever(key: str, kb_dir: Path = DEFAULT_KB_DIR) -> BM25Retriever:
    """部門顧問的知識庫：行銷沿用行銷模組知識庫（加上美宣）；其他部門用各自資料夾，再加上全社團共用的校園規範。
    自訂部門只用共用的校園規範。"""
    if key == "marketing":
        retriever = BM25Retriever.from_directory(kb_dir)
        design = kb_dir / "departments" / "design.md"
        if design.exists():
            retriever = BM25Retriever([*retriever.chunks, *split_markdown(design.name, design.read_text(encoding="utf-8"))])
        return retriever
    chunks: list[Chunk] = []
    for path in sorted((kb_dir / "departments").glob(f"{key}.md")) if key in DEPARTMENTS else []:
        chunks.extend(split_markdown(path.name, path.read_text(encoding="utf-8")))
    for name in SHARED_KB_FILES:
        path = kb_dir / name
        if path.exists():
            chunks.extend(split_markdown(path.name, path.read_text(encoding="utf-8")))
    return BM25Retriever(chunks)
