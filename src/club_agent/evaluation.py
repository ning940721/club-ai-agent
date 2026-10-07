"""成果評鑑工具（對應企劃書「壓力測試與指標建立」）。

- 時間節省率：記錄每次任務「傳統手寫」與「AI 輔助生成再微調」的耗時，目標節省 60% 以上。
- 實際宣傳成效：比較導入 AI 建議前後的觸及率與互動率。
- 質化評分：記錄幹部對產出的吸引力、貼合度等主觀評分。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, Field

from .metrics import MetricsSummary

TIME_SAVING_TARGET = 0.60


class TrialRecord(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    club: str
    task: str = Field(description="任務描述，如：週年大成宣傳文案")
    manual_minutes: float = Field(description="傳統方式所需時間（分鐘）")
    ai_minutes: float = Field(description="使用 AI 輔助生成再微調所需時間（分鐘）")
    attractiveness: int | None = Field(default=None, description="內容吸引力 1–5")
    fit: int | None = Field(default=None, description="客製化貼合度 1–5")
    notes: str = ""

    @property
    def time_saving(self) -> float:
        return 1 - self.ai_minutes / self.manual_minutes if self.manual_minutes else 0.0


def append_trial(path: str | Path, record: TrialRecord) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(record.model_dump_json() + "\n")


def load_trials(path: str | Path) -> list[TrialRecord]:
    p = Path(path)
    if not p.exists():
        return []
    return [TrialRecord(**json.loads(line)) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def trials_report(trials: list[TrialRecord]) -> str:
    if not trials:
        return "尚無實測紀錄。"
    avg_saving = mean(t.time_saving for t in trials)
    lines = [
        f"實測次數：{len(trials)}",
        f"平均時間節省率：{avg_saving:.1%}（目標 {TIME_SAVING_TARGET:.0%}，{'達標' if avg_saving >= TIME_SAVING_TARGET else '未達標'}）",
    ]
    for label, attr in (("內容吸引力", "attractiveness"), ("客製化貼合度", "fit")):
        scores = [getattr(t, attr) for t in trials if getattr(t, attr) is not None]
        if scores:
            lines.append(f"平均{label}：{mean(scores):.2f} / 5（{len(scores)} 筆）")
    lines.append("")
    lines += [
        f"- {t.timestamp[:10]} {t.club}｜{t.task}：{t.manual_minutes:g} → {t.ai_minutes:g} 分鐘（節省 {t.time_saving:.0%}）"
        for t in trials
    ]
    return "\n".join(lines)


def compare_metrics(before: MetricsSummary, after: MetricsSummary) -> str:
    def change(a: float | None, b: float | None) -> str:
        return f"{(b - a) / a:+.1%}" if a and b is not None else "N/A"

    def num(v: float | None) -> str:
        return "—" if v is None else f"{v:.0f}"

    def pct(v: float | None) -> str:
        return "—" if v is None else f"{v:.2%}"

    return "\n".join(
        [
            "| 指標 | 導入前 | 導入後 | 變化 |",
            "|---|---|---|---|",
            f"| 貼文數 | {before.total_posts} | {after.total_posts} | |",
            f"| 平均觸及 | {num(before.avg_reach)} | {num(after.avg_reach)} | {change(before.avg_reach, after.avg_reach)} |",
            f"| 平均互動率 | {pct(before.avg_engagement_rate)} | {pct(after.avg_engagement_rate)} "
            f"| {change(before.avg_engagement_rate, after.avg_engagement_rate)} |",
        ]
    )
