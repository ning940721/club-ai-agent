"""社長 Agent：彙整各部門進度、找出卡關事項，並產生下次會議議程。"""

from __future__ import annotations

from datetime import date

from ..departments import ClubSettings
from ..llm import LLM
from ..schemas import ClubProfile, ProgressBrief

SYSTEM_PROMPT = """你是學生社團社長的幕僚，負責掌握各部門進度並準備幹部會議。

工作原則：
- 只根據提供的任務、紀錄與會議重點整理，不要捏造進度。
- 每個啟用的部門都要列出；沒有資料的部門寫「目前沒有紀錄」，並建議請該部門更新進度。
- 逾期、卡關或需要其他部門配合的事項放在 blockers，並在議程中安排討論。
- 議程順序：上次待辦追蹤 → 需要決議的事項 → 各部門報告 → 其他；總長度控制在 60–90 分鐘。
- 全部使用繁體中文。"""


class ProgressReporter:
    def __init__(self, llm: LLM):
        self.llm = llm

    def build_prompt(
        self,
        club: ClubProfile,
        settings: ClubSettings,
        tasks_text: str,
        records_text: str,
        meetings_text: str,
        today: date,
    ) -> str:
        return f"""<today>{today.isoformat()}</today>

<club>{club.name}：{club.positioning}</club>

<departments>
{settings.all_details_text()}
</departments>

<tasks>
{tasks_text}
</tasks>

<recent_department_activity>
{records_text or "（沒有紀錄）"}
</recent_department_activity>

<recent_meetings>
{meetings_text}
</recent_meetings>

請彙整各部門目前進度，並規劃下次幹部會議的議程。"""

    def run(
        self,
        club: ClubProfile,
        settings: ClubSettings,
        tasks_text: str,
        records_text: str,
        meetings_text: str,
        today: date | None = None,
    ) -> ProgressBrief:
        prompt = self.build_prompt(club, settings, tasks_text, records_text, meetings_text, today or date.today())
        return self.llm.structured(SYSTEM_PROMPT, prompt, ProgressBrief)
