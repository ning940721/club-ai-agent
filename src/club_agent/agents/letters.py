"""信件 Agent：依情境撰寫給講者、合作對象的信件，或給社員的宣傳通知。"""

from __future__ import annotations

from ..llm import LLM
from ..schemas import ClubProfile, Letter

SYSTEM_PROMPT = """你是學生社團的文書幕僚，替社團幹部撰寫對外信件與對內通知。

工作原則：
- 只使用提供的資訊；沒有提供的日期、金額、地點、人數等一律寫【待補：…】，絕不捏造。
- 對外信件（給講者、廠商、校友）：語氣有禮、簡潔，開頭說明社團與來意，清楚列出需要對方確認或回覆的事項與回覆期限，
  結尾署名「社團名稱＋部門＋聯絡人【待補】」。
- 對內通知（給社員）：語氣親切有吸引力，開頭點出亮點，清楚寫出時間、地點、報名方式，適合貼在 IG 或社團群組。
- short_text 是可以直接貼到 LINE 的短版，保留時間地點等關鍵資訊。
- 全部使用繁體中文。"""


class LetterWriter:
    def __init__(self, llm: LLM):
        self.llm = llm

    def run(self, club: ClubProfile, sender: str, kind: str, guide: str, facts: str, extra: str = "") -> Letter:
        prompt = f"""<club>{club.name}：{club.positioning}；主要對象：{club.target_audience}</club>
<sender>{club.name} {sender}</sender>

<letter_type>{kind}：{guide}</letter_type>

<facts>
{facts}
</facts>

<extra_instructions>
{extra or "（無）"}
</extra_instructions>

請撰寫這封{kind}。"""
        return self.llm.structured(SYSTEM_PROMPT, prompt, Letter)
