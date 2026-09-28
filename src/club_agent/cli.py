"""命令列介面。

  club-agent metrics  --posts examples/sample_posts.csv
  club-agent diagnose --club examples/club_profile.json --posts examples/sample_posts.csv
  club-agent campaign --club examples/club_profile.json --brief "..." [--posts ...]
  club-agent search   "週年活動 宣傳時程"
  club-agent eval log | report | compare
  club-agent personas
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import evaluation
from .metrics import load_posts_csv, summarize
from .personas import PERSONAS
from .report import campaign_markdown, diagnosis_markdown
from .retriever import BM25Retriever
from .schemas import ClubProfile

DEFAULT_TRIALS = "outputs/trials.jsonl"


def _load_club(path: str) -> ClubProfile:
    return ClubProfile(**json.loads(Path(path).read_text(encoding="utf-8")))


def _save(out_dir: str, stem: str, markdown: str, data: str) -> Path:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    md = d / f"{stem}-{stamp}.md"
    md.write_text(markdown, encoding="utf-8")
    (d / f"{stem}-{stamp}.json").write_text(data, encoding="utf-8")
    return md


def _progress(msg: str) -> None:
    print(f"… {msg}", file=sys.stderr)


def _workflow(args):
    from .llm import create_llm
    from .workflow import MarketingWorkflow

    return MarketingWorkflow(
        llm=create_llm(args.provider, args.model),
        retriever=BM25Retriever.from_directory(args.kb) if args.kb else BM25Retriever.from_directory(),
        max_rounds=getattr(args, "rounds", 3),
        on_progress=_progress,
    )


def cmd_metrics(args) -> None:
    print(summarize(load_posts_csv(args.posts)).to_prompt_text())


def cmd_diagnose(args) -> None:
    club = _load_club(args.club)
    metrics = summarize(load_posts_csv(args.posts))
    report = _workflow(args).diagnose(club, metrics, args.concern)
    md = diagnosis_markdown(club.name, report)
    path = _save(args.out, "diagnosis", md, report.model_dump_json(indent=2))
    print(md)
    print(f"已儲存：{path}", file=sys.stderr)


def cmd_campaign(args) -> None:
    club = _load_club(args.club)
    wf = _workflow(args)
    diagnosis = None
    if args.posts:
        diagnosis = wf.diagnose(club, summarize(load_posts_csv(args.posts)), args.concern)
    result = wf.campaign(club, args.brief, diagnosis)
    md = campaign_markdown(result)
    path = _save(args.out, "campaign", md, result.model_dump_json(indent=2))
    print(md)
    print(f"已儲存：{path}", file=sys.stderr)


def cmd_search(args) -> None:
    retriever = BM25Retriever.from_directory(args.kb) if args.kb else BM25Retriever.from_directory()
    for chunk in retriever.search(args.query, k=args.k):
        print(chunk.render(), end="\n\n")


def cmd_personas(_args) -> None:
    for p in PERSONAS.values():
        print(f"[{'可用' if p.available else '規劃中'}] {p.key:<13} {p.title}：{p.description}")


def cmd_eval_log(args) -> None:
    record = evaluation.TrialRecord(
        club=args.club_name,
        task=args.task,
        manual_minutes=args.manual,
        ai_minutes=args.ai,
        attractiveness=args.attractiveness,
        fit=args.fit,
        notes=args.notes,
    )
    evaluation.append_trial(args.file, record)
    print(f"已記錄，本次時間節省率 {record.time_saving:.0%}")


def cmd_eval_report(args) -> None:
    print(evaluation.trials_report(evaluation.load_trials(args.file)))


def cmd_eval_compare(args) -> None:
    before = summarize(load_posts_csv(args.before))
    after = summarize(load_posts_csv(args.after))
    print(evaluation.compare_metrics(before, after))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="club-agent", description="校園社團 AI 營運顧問｜行銷宣傳與數據診斷模組")
    sub = parser.add_subparsers(dest="command", required=True)

    def llm_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--provider", choices=["gemini", "claude"], help="模型供應商（預設讀取 CLUB_AGENT_PROVIDER，否則為 gemini）")
        p.add_argument("--model", help="模型 ID（預設讀取 CLUB_AGENT_MODEL；Gemini 為 gemini-flash-latest，Claude 為 claude-opus-5）")
        p.add_argument("--kb", help="自訂知識庫資料夾（預設使用內建知識庫）")
        p.add_argument("--out", default="outputs", help="輸出資料夾")

    p = sub.add_parser("metrics", help="只計算社群數據統計（不呼叫 AI）")
    p.add_argument("--posts", required=True)
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("diagnose", help="情境 A：社群數據診斷與策略")
    p.add_argument("--club", required=True, help="社團資料 JSON")
    p.add_argument("--posts", required=True, help="貼文數據 CSV")
    p.add_argument("--concern", default="", help="目前的宣傳困擾")
    llm_opts(p)
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("campaign", help="情境 B：活動宣傳企劃與文案生成")
    p.add_argument("--club", required=True)
    p.add_argument("--brief", required=True, help="活動需求描述（主題、日期、地點、目標等）")
    p.add_argument("--posts", help="可選：附上貼文數據，先做診斷再擬定策略")
    p.add_argument("--concern", default="")
    p.add_argument("--rounds", type=int, default=3, help="最多審查修訂輪數")
    llm_opts(p)
    p.set_defaults(func=cmd_campaign)

    p = sub.add_parser("search", help="測試知識庫檢索")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=3)
    p.add_argument("--kb")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("personas", help="列出顧問角色")
    p.set_defaults(func=cmd_personas)

    ev = sub.add_parser("eval", help="成果評鑑紀錄").add_subparsers(dest="eval_command", required=True)
    p = ev.add_parser("log", help="記錄一次實測（時間節省與主觀評分）")
    p.add_argument("--club-name", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--manual", type=float, required=True, help="傳統方式耗時（分鐘）")
    p.add_argument("--ai", type=float, required=True, help="AI 輔助耗時（分鐘）")
    p.add_argument("--attractiveness", type=int, choices=range(1, 6))
    p.add_argument("--fit", type=int, choices=range(1, 6))
    p.add_argument("--notes", default="")
    p.add_argument("--file", default=DEFAULT_TRIALS)
    p.set_defaults(func=cmd_eval_log)
    p = ev.add_parser("report", help="彙整實測結果")
    p.add_argument("--file", default=DEFAULT_TRIALS)
    p.set_defaults(func=cmd_eval_report)
    p = ev.add_parser("compare", help="比較導入前後的社群成效")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.set_defaults(func=cmd_eval_compare)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
