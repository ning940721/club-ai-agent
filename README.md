# 校園社團 AI 營運顧問（club-ai-agent）

**115-1 NTU Challengers #PBL #AI Agent**
專案主題：基於 AI Agent 之校園學生社團全方位營運顧問與專案優化系統

本期聚焦 **「行銷宣傳與數據診斷」模組**：輸入社團的社群數據與活動需求，由三個 AI Agent 協同產出數據診斷、宣傳時程與多平台貼文文案，並自動審查品質。

```
            社群數據 CSV ──► 統計分析（程式計算，避免幻覺）
                                   │
  社團資料 ─┬──────────────────────▼
            │            ┌─────────────────────┐     ┌─────────────┐
            ├──────────► │ 數據診斷 Agent       │ ◄── │ RAG 知識庫   │
            │            └─────────┬───────────┘     │ 演算法規律   │
            │                      ▼ 診斷報告         │ 文案範本     │
  活動需求 ─┼──────────► ┌─────────────────────┐ ◄── │ 宣傳時程     │
            │            │ 文案與策略 Agent     │     │ 校園規範     │
            │            └─────────┬───────────┘     └─────────────┘
            │                      ▼ 宣傳企劃
            │            ┌─────────────────────┐
            └──────────► │ 經營審查 Agent       │── 未達標 ──► 退回修訂（最多 N 輪）
                         └─────────┬───────────┘
                                   ▼ 通過
                         Markdown 企劃書 + JSON
```

## 快速開始

```bash
pip install -e ".[dev]"
export GEMINI_API_KEY=你的金鑰             # 到 Google AI Studio 申請

# 不需 API 金鑰：先看統計與知識庫檢索
club-agent metrics --posts examples/sample_posts.csv
club-agent search "週年大成 宣傳時程"

# 情境 A：社群數據診斷與策略
club-agent diagnose \
  --club examples/club_profile.json \
  --posts examples/sample_posts.csv \
  --concern "最近三個月觸及一直掉，不知道該發什麼"

# 情境 B：活動宣傳企劃與文案生成（附數據時會先診斷再擬策略）
club-agent campaign \
  --club examples/club_profile.json \
  --brief "跨校社團聯展：12/20（六）13:00-18:00，地點【待確認】，免費入場，目標 300 人參觀" \
  --posts examples/sample_posts.csv
```

結果會輸出到終端機，並存成 `outputs/*.md`（給幹部閱讀）與 `outputs/*.json`（供後續分析）。

> `examples/` 內的社團資料與貼文數據皆為**虛構示範資料**，實測時請換成實際社團資料。

## 網頁版

給不熟悉指令的社團幹部使用：上傳 CSV、填活動資訊、按按鈕就能拿到報告，支援手機瀏覽。

```bash
pip install -r requirements.txt
streamlit run app.py
```

免費上線到網路（金鑰不外流、可設使用密碼）的步驟見 **[docs/deploy.md](docs/deploy.md)**。

## 輸入資料格式

**社團資料**（`club_profile.json`）：`name`、`category`、`positioning`、`target_audience`、`brand_voice`、`platforms`、`monthly_budget_ntd`、`notes`。

**貼文數據**（CSV，可由 IG／FB 洞察報告整理）：

| 欄位 | 說明 |
|---|---|
| date / time | 發文日期 `YYYY-MM-DD`、時間 `HH:MM` |
| platform | Instagram / Facebook / Dcard … |
| post_type | 圖文、輪播、Reels、公告、限動 … |
| topic | 活動宣傳、社課花絮、作品分享 … |
| reach, likes, comments, shares, saves | 觸及與各項互動數 |
| followers | 發文當下粉絲數 |
| caption | 貼文內文（可選） |

互動率定義：（按讚＋留言＋分享＋收藏）÷ 觸及人數。

## 成果評鑑

對應企劃書的量化與質化指標：

```bash
# 每次實測後記錄耗時與主觀評分（目標：節省 60% 以上時間）
club-agent eval log --club-name 攝影社 --task "聯展宣傳文案" --manual 180 --ai 50 --attractiveness 4 --fit 4
club-agent eval report

# 比較導入 AI 建議前後的觸及與互動率
club-agent eval compare --before data/before.csv --after data/after.csv
```

## 專案結構

```
src/club_agent/
  agents/diagnostic.py   數據診斷 Agent
  agents/drafting.py     文案與策略 Agent
  agents/critic.py       經營審查 Agent（評分表＋程式判定門檻）
  workflow.py            多 Agent 協同流程（撰寫 → 審查 → 修訂迴圈）
  metrics.py             社群數據統計
  retriever.py           RAG 檢索（BM25，可替換為向量資料庫）
  knowledge_base/*.md    知識庫（種子資料，請持續擴充）
  llm.py                 AI 模型呼叫層（Gemini／Claude，可切換）
  personas.py            顧問角色（行銷已開放；公關、財務、組織、營運規劃中）
  evaluation.py          成果評鑑工具
  report.py              Markdown 報告輸出
  cli.py                 命令列介面
docs/                    架構說明、開發日誌、後續規劃
tests/                   單元測試（使用假 LLM，不需 API 金鑰）
```

## 擴充知識庫

在 `src/club_agent/knowledge_base/` 新增 Markdown 檔即可，系統以 `##`／`###` 標題切塊檢索。
建議收錄：社團歷屆高互動貼文（標註互動率）、成功活動的宣傳時程、校內正式宣傳規定。
也可用 `--kb 資料夾路徑` 指定社團專屬知識庫。

## 常見問題

| 訊息 | 原因與解法 |
|---|---|
| 找不到 API 金鑰 | 尚未設定 `GEMINI_API_KEY`。Windows 命令提示字元：`set GEMINI_API_KEY=金鑰`；PowerShell：`$env:GEMINI_API_KEY="金鑰"`；Mac：`export GEMINI_API_KEY="金鑰"`。永久設定可用 `setx GEMINI_API_KEY "金鑰"`（需重開終端機） |
| 某模型目前忙碌（503／429） | Google 伺服器暫時滿載。程式會自動等待重試，再依序改用備用模型（預設 `gemini-2.5-flash`、`gemini-flash-lite-latest`，可用 `CLUB_AGENT_FALLBACK_MODELS` 修改）。全部失敗時請稍後再試 |
| 檔案名稱、目錄名稱或磁碟區標籤語法錯誤 | 在「命令提示字元」輸入了 PowerShell 語法，請改用上方對應的寫法 |

## 開發

```bash
pytest
```

## 切換 AI 模型

預設使用 **Google Gemini**（`gemini-flash-latest`），也支援 Anthropic Claude。

| 設定方式 | Gemini（預設） | Claude |
|---|---|---|
| 安裝 | `pip install -e .` | `pip install -e ".[claude]"` |
| 金鑰 | `GEMINI_API_KEY` | `ANTHROPIC_API_KEY` |
| 指定供應商 | — | `--provider claude` 或 `CLUB_AGENT_PROVIDER=claude` |
| 預設模型 | `gemini-flash-latest` | `claude-opus-5` |

換模型：`--model gemini-pro-latest` 或設定環境變數 `CLUB_AGENT_MODEL`。
要新增其他供應商，只需在 `llm.py` 實作 `structured()` 並登錄到 `PROVIDERS`。
