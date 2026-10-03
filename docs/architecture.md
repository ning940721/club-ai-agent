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

- 以 `create_llm(provider, model)` 建立；預設 `GeminiLLM`，可切換 `ClaudeLLM`。
- `GeminiLLM` 將 Pydantic schema 展開成獨立 JSON Schema，透過 `response_json_schema` 要求 Gemini 輸出 JSON，
  再以 Pydantic 驗證；輸出被截斷、被擋或格式不符時拋出 `LLMError`。
- `ClaudeLLM` 使用 `client.beta.messages.parse`，搭配 adaptive thinking 與 effort 設定。
- （Claude）啟用伺服器端 refusal fallback（`fallbacks="default"`），請求被安全分類器誤擋時自動改由備援模型處理。
- （Claude）`stop_reason` 為 `refusal` 或 `max_tokens` 時拋出 `LLMError`，不會回傳不完整的結果。

## 多社團與部門顧問（v0.4.0）

- `store.py`：`ClubStore` 介面，目前實作 `LocalClubStore`（本機檔案）。每個社團一組帳號，密碼以 PBKDF2 加鹽雜湊保存；
  紀錄（部門、類型、標題、摘要、完整內容）存在各社團自己的資料夾，彼此隔離。
- `departments.py`：七個部門（行銷、公關、財務、活動、場地、會議記錄、課程）的顧問角色、專長與範例問題。
  行銷沿用行銷模組知識庫；其他部門使用 `knowledge_base/departments/<key>.md`，再加上共用的校園規範。
- `agents/advisor.py`：部門顧問 Agent，輸入社團資料、部門知識庫與「其他部門近期動態」，輸出 `Advice`
  （摘要、行動步驟、可直接使用的文件模板、跨部門協作、注意事項、需要補充的資訊）。
- 網頁版登入後選擇部門；所有產出都寫入社團紀錄，「社團動態」頁可看到全社團各部門的提問與成果。

### 下一階段：線上資料庫

實作一個新的 `ClubStore`（例如 Supabase），提供相同的方法（建立帳號、登入驗證、讀寫社團資料與紀錄），
再在 `app.py` 換掉 `LocalClubStore` 即可，部門顧問與行銷工具都不需修改。

## 新增或深化部門

1. 在 `departments.py` 調整該部門的顧問角色、專長與範例問題；正式版把 `beta` 改為 `False`。
2. 在 `knowledge_base/departments/` 補充該部門的知識（例如社團歷屆預算表、公關信）。
3. 需要專屬工具時（像行銷的數據診斷），在 `schemas.py` 定義輸出格式、在 `agents/` 新增 Agent，再加到網頁的部門分頁。
