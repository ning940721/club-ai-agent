"""課程 Agent：依學期目標與學員程度規劃社課課表。"""

from __future__ import annotations

from ..llm import LLM
from ..retriever import Retriever, format_context
from ..schemas import ClubProfile, CoursePlan

SYSTEM_PROMPT = """你是學生社團的社課規劃顧問，替課程幹部規劃一學期的社課。

工作原則：
- 先依學期目標倒推，課程難度循序漸進；每堂課都要有「帶得走的收穫」。
- 堂數必須等於要求的堂數；期中安排一次成果分享或交流，維持參與動機。
- 活動以實作與互動為主，避免整堂單向講授；時間分配加總要符合每堂課的長度。
- 材料與器材寫具體，社團可能沒有的器材要提醒借用或替代方案。
- 參考知識庫的實務做法，但以社團資訊為主。
- 全部使用繁體中文。"""


class CoursePlanner:
    def __init__(self, llm: LLM, retriever: Retriever | None = None):
        self.llm = llm
        self.retriever = retriever

    def plan(self, club: ClubProfile, goal: str, level: str, count: int, minutes: int, details: str = "", extra: str = "") -> CoursePlan:
        knowledge = format_context(self.retriever.search(f"社課規劃 {goal} {level}", k=3)) if self.retriever else ""
        prompt = f"""<club>{club.name}：{club.positioning}；主要對象：{club.target_audience}</club>

<course_department_details>
{details or "（未填寫）"}
</course_department_details>

<requirements>
學期目標：{goal or "未填"}
學員程度：{level or "未填"}
堂數：{count} 堂
每堂課長度：{minutes} 分鐘
補充：{extra or "（無）"}
</requirements>

<knowledge>
{knowledge or "（無）"}
</knowledge>

請規劃這學期的社課。"""
        return self.llm.structured(SYSTEM_PROMPT, prompt, CoursePlan)
