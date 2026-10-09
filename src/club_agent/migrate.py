"""把這台電腦上的社團資料（data/clubs）搬到線上資料庫（Supabase）。

用法（在專案資料夾）：
    python -m club_agent.migrate              # 線上已經有的社團帳號會略過
    python -m club_agent.migrate --overwrite  # 用這台電腦的資料覆蓋線上的社團帳號與資料

連線設定從 .streamlit/secrets.toml 的 SUPABASE_URL、SUPABASE_KEY 讀取（也可以用環境變數）。
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

from .store import LocalClubStore, StoreError
from .supabase_store import SupabaseClubStore, migrate_local

ROOT = Path(__file__).resolve().parents[2]


def load_secrets(path: Path = ROOT / ".streamlit" / "secrets.toml") -> dict:
    secrets = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k: os.environ.get(k) or secrets.get(k) for k in ("SUPABASE_URL", "SUPABASE_KEY", "CLUB_AGENT_DATA_DIR")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把本機的社團資料搬到線上資料庫（Supabase）")
    parser.add_argument("--overwrite", action="store_true", help="線上已經有同一個社團帳號時，用本機資料覆蓋")
    args = parser.parse_args(argv)
    config = load_secrets()
    if not config["SUPABASE_URL"] or not config["SUPABASE_KEY"]:
        print("找不到 SUPABASE_URL 或 SUPABASE_KEY。請先在 .streamlit/secrets.toml 填入（見 docs/deploy.md）。")
        return 1
    local = LocalClubStore(config["CLUB_AGENT_DATA_DIR"] or ROOT / "data")
    remote = SupabaseClubStore.connect(config["SUPABASE_URL"], config["SUPABASE_KEY"])
    try:
        stats = migrate_local(local, remote, overwrite=args.overwrite)
    except StoreError as e:
        print(str(e))
        return 1
    print(f"完成：搬移 {stats['clubs']} 個社團、{stats['docs']} 筆資料、{stats['records']} 筆分享的成果；略過 {stats['skipped']} 個社團。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
