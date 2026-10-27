"""定時喚醒網站與 Supabase，避免免費方案休眠／暫停（由 GitHub Actions 執行）。

用法：python scripts/keep_awake.py
環境變數：
  APP_URL                網站網址（預設 https://club-agent.streamlit.app/）
  SUPABASE_URL           Supabase Project URL（沒設定就略過資料庫）
  SUPABASE_PUBLIC_KEY    anon 或 publishable 金鑰（只讀不到資料，安全）
"""

from __future__ import annotations

import os
import sys
import urllib.request

WAKE_BUTTON = "get this app back up"


def wake_streamlit(url: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(10_000)

        # 休眠中的網站會顯示喚醒按鈕；按鈕可能在主頁或 iframe 裡
        clicked = False
        for frame in page.frames:
            button = frame.get_by_role("button", name=WAKE_BUTTON)
            if button.count():
                button.first.click()
                clicked = True
                break

        if clicked:
            print("網站在休眠中，已按下喚醒按鈕，等待啟動…")
            page.wait_for_timeout(120_000)
        else:
            print("網站醒著，已造訪一次。")
            page.wait_for_timeout(15_000)
        browser.close()


def ping_supabase(base_url: str, key: str) -> None:
    base_url = base_url.rstrip("/").removesuffix("/rest/v1")
    req = urllib.request.Request(
        f"{base_url}/rest/v1/clubs?select=club_id&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"Supabase 回應 {resp.status}，資料庫保持啟用。")


def main() -> int:
    ok = True

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = os.environ.get("SUPABASE_PUBLIC_KEY", "").strip()
    if supabase_url and supabase_key:
        try:
            ping_supabase(supabase_url, supabase_key)
        except Exception as exc:  # noqa: BLE001
            print(f"Supabase 失敗：{exc}（專案可能已被暫停，請到 Supabase 按 Restore）")
            ok = False
    else:
        print("沒有設定 SUPABASE_URL／SUPABASE_PUBLIC_KEY，略過資料庫。")

    app_url = os.environ.get("APP_URL", "").strip() or "https://club-agent.streamlit.app/"
    try:
        wake_streamlit(app_url)
    except Exception as exc:  # noqa: BLE001
        print(f"喚醒網站失敗：{exc}")
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
