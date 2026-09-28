# 系統架構說明

## 設計原則

1. **數字由程式算，解讀交給 AI**：`metrics.py` 先計算互動率、各主題／形式／時段表現與月度趨勢，
   Agent 只負責解讀與提出建議，並被要求引用這些數字作為證據，降低 AI 幻覺。
2. **結構化交接**：三個 Agent 之間以 Pydantic schema（`schemas.py`）交換資料，
   透過 Claude Structured Outputs 保證輸出可解析，方便串接、存檔與後續統計。
3. **審查標準一致**：Critic Agent 依固定評分表給分，但「是否通過」由程式依門檻判定
   （平均 ≥ 4.0 且每項 ≥ 3），不讓模型自行放水。
4. **不捏造資訊**：未提供的日期、地點、價格一律以【待補：…】標示；審查時若發現捏造，資訊完備度最多 2 分。
5. **可替換元件**：`LLM` 與 `Retriever` 皆為介面，測試時用假 LLM；知識庫檢索之後可改用向量資料庫。

## 三個 Agent

| Agent | 輸入 | 輸出 | 對應實測情境 |
|---|---|---|---|
| 數據診斷 Diagnostic | 社團資料、數據統計、困擾描述、知識庫 | `DiagnosisReport`：瓶頸、受眾洞察、主題分配、最佳發文時機、優先行動、數據限制 | 情境 A |
| 文案與策略 Drafting | 社團資料、活動需求、診斷報告、知識庫、（修訂時）上一版與審查意見 | `CampaignPlan`：多階段時程、各平台貼文、限動腳本、預算、KPI | 情境 B |
| 經營審查 Critic | 社團資料、活動需求、企劃 | `Critique`：六項評分、優點、修改要求 | 品質把關 |

### 審查評分表

| 項目 | 檢查重點 |
|---|---|
| 內容吸引力 | 開頭 3 秒抓住注意力、具擴散動機 |
| 資訊完備度 | 時間地點費用報名方式完整、未知資訊誠實標示 |
| CTA 明確度 | 單一、具體、含期限 |
| 客製化與貼合度 | 貼合社團定位語氣受眾、依平台調整 |
| 時程可執行性 | 階段合理、分工清楚、避開考試週 |
| 品牌與預算一致性 | 符合品牌形象、不超出預算 |

## RAG 知識庫

- 目前以 BM25（中文字元二元組斷詞）檢索 Markdown 知識庫，零外部依賴、可離線運作。
- 知識庫依 `##`／`###` 標題切塊，每個 Agent 依任務組合查詢字串取回前 k 塊，放入 `<knowledge_base>` 區段。
- 若知識庫規模擴大（例如收錄數百篇歷屆貼文），可實作 `Retriever` 介面改用 embedding + 向量資料庫。

## 模型呼叫

- `ClaudeLLM` 使用 `client.beta.messages.parse`，搭配 adaptive thinking 與 effort 設定。
- 啟用伺服器端 refusal fallback（`fallbacks="default"`），請求被安全分類器誤擋時自動改由備援模型處理。
- `stop_reason` 為 `refusal` 或 `max_tokens` 時拋出 `LLMError`，不會回傳不完整的結果。

## 擴充到其他營運面向

`personas.py` 已登錄公關贊助、財務、組織人事、營運統籌等角色。新增模組的步驟：
1. 在 `schemas.py` 定義該模組的輸入與輸出格式（例如 `SponsorshipProposal`、`BudgetSheet`）。
2. 在 `agents/` 新增對應 Agent 與 system prompt，沿用「產出 → 審查 → 修訂」流程。
3. 在 `knowledge_base/` 補上領域知識（公關信範本、預算表範例等）。
4. 將 persona 設為 `available=True` 並加入 CLI 子命令。
