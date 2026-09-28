"""顧問角色定義（彈性角色切換與模組化擴充）。

系統的長期目標是涵蓋社團各營運面向。本期實作「行銷宣傳與數據診斷」模組，
其餘角色先登錄於此以保留擴充介面，之後只要補上對應 Agent 與知識庫即可啟用。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    key: str
    title: str
    description: str
    available: bool


PERSONAS: dict[str, Persona] = {
    p.key: p
    for p in [
        Persona("marketing", "社群行銷專家", "社群數據診斷、宣傳企劃、多平台文案生成與審查", True),
        Persona("sponsorship", "公關贊助顧問", "企業贊助提案、公關信模板、合作洽談策略", False),
        Persona("finance", "財務健檢師", "預算編列、記帳邏輯、成本控管與預算表模板", False),
        Persona("organization", "組織人事顧問", "幹部交接文件、招募與留任機制", False),
        Persona("operations", "營運統籌顧問", "跨部門時程規劃、場地租借流程", False),
    ]
}


def get_persona(key: str) -> Persona:
    try:
        persona = PERSONAS[key]
    except KeyError:
        raise ValueError(f"未知的顧問角色：{key}（可用：{', '.join(PERSONAS)}）") from None
    if not persona.available:
        raise NotImplementedError(f"「{persona.title}」模組尚在規劃中，本期僅開放社群行銷專家")
    return persona
