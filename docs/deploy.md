# 正式上線教學

上線後會得到一個網址，幹部用手機或電腦打開、登入社團帳號就能使用。
目前的正式網址：**<https://club-agent.streamlit.app/>**
整個流程分三步，都是免費方案：

1. **Supabase**：線上資料庫，存放社團帳號與所有資料（主機重新啟動也不會消失）
2. **把電腦上的資料搬到線上資料庫**
3. **Streamlit Community Cloud**：網站主機，從 GitHub 讀取程式並執行

> 介面文字可能隨服務更新而略有不同，找對應的選項即可。

---

## 一、建立線上資料庫（Supabase）

1. 到 **supabase.com** → Start your project → 用 GitHub 帳號登入。
2. 按「New project」：
   - Name：例如 `club-agent`
   - Database Password：按 Generate 產生，**存在安全的地方**（之後通常用不到）
   - Region：選離台灣近的，例如 **Northeast Asia (Tokyo)** 或 **Southeast Asia (Singapore)**
   - 按 Create new project，等 1–2 分鐘建立完成。
3. 建立資料表與文件庫的檔案空間：左側 **SQL Editor** → New query → 把專案裡 `docs/supabase_schema.sql` 的內容全部貼上 → 按 **Run**，看到 Success 即可。
   （之後若 `supabase_schema.sql` 有更新，再貼一次執行即可，已經存在的資料不受影響。）
4. 取得連線資料：左側 **Project Settings**（齒輪）→
   - **Data API**：複製 **Project URL**（像 `https://abcdefgh.supabase.co`；後面若多了 `/rest/v1/` 也沒關係，系統會自動去掉）
   - **API Keys**：複製 **service_role** 金鑰（在「Legacy API Keys」分頁，按 Reveal 顯示），或新版的 **secret key**（`sb_secret_` 開頭）
   - ⚠️ 這把金鑰可以讀寫所有資料，**只能放在 Secrets**，不要貼到 LINE、GitHub 或任何公開的地方。

> 免費專案如果**連續一週沒有人使用**會被暫停，資料不會消失；到 Supabase 專案頁按 Restore 就能恢復。

## 二、把電腦上的資料搬到線上資料庫

1. 用記事本打開專案資料夾的 `.streamlit/secrets.toml`，加上兩行（換成你的值）：
   ```toml
   SUPABASE_URL = "https://abcdefgh.supabase.co"
   SUPABASE_KEY = "剛才複製的 service_role 或 secret 金鑰"
   ```
2. 雙擊專案資料夾裡的 **「搬資料到線上資料庫.bat」**，看到「完成：搬移 1 個社團…」就成功了（文件庫的檔案也會一起搬）。
   - 電腦上的資料不會被刪除；重複執行時，線上已經有的社團會略過。
3. 之後在自己電腦雙擊「啟動網頁」也會改用線上資料庫（登入頁下方會顯示「資料存放：線上資料庫」），
   和網站上看到的是同一份資料。想改回存在電腦上，刪掉這兩行即可。

## 三、部署網站（Streamlit Community Cloud）

1. 到 **share.streamlit.io** → 用 GitHub 帳號登入，同意授權存取 `club-ai-agent`。
2. 按「Create app」→ 選擇從 GitHub 部署，填入：
   - Repository：`ning940721/club-ai-agent`
   - Branch：`claude/planning-document-creation-76lhic`（合併到 main 之後改成 `main`）
   - Main file path：`app.py`
   - App URL：可以自訂網址名稱，例如 `ntu-photo-club`
3. 展開「Advanced settings」：
   - Python version：選 **3.12**
   - **Secrets** 貼上（換成你的值）：
     ```toml
     GEMINI_API_KEY = "你的 Gemini 金鑰"
     SUPABASE_URL = "https://abcdefgh.supabase.co"
     SUPABASE_KEY = "service_role 或 secret 金鑰"
     SIGNUP_CODE = "自訂一組邀請碼"
     ```
4. 按「Deploy」，第一次安裝約需 3–5 分鐘，完成後就會看到登入頁，網址列就是要分享給幹部的網址。
5. 確認：登入頁下方顯示「**資料存放：線上資料庫**」，用原本的社團帳號密碼登入，資料都在。

## 改用 Claude（選用）

1. 到 **console.anthropic.com** 註冊 → **Billing** 儲值（預付制，可設定每月上限）→ **API Keys** → Create Key，複製金鑰。
2. 在網站的 Secrets（以及電腦上的 `.streamlit/secrets.toml`，如果也想在電腦上用）加上：
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   CLAUDE_MODEL = "claude-opus-5-5"
   ```
   有 `ANTHROPIC_API_KEY` 時網站會自動改用 Claude；想改回 Gemini，加上 `AI_PROVIDER = "gemini"` 或刪掉 Claude 金鑰即可。
3. 模型選擇：`claude-opus-5-5`（品質最好，預設）、`claude-sonnet-5-5`（較快、價格約一半）、`claude-haiku-5-5`（最快、最便宜）。
   `CLAUDE_EFFORT` 可設 `low`／`medium`／`high`，越低越快；問答類工作固定用 `low`。

## 之後怎麼更新

- 程式推送到 GitHub 的同一個分支後，網站會自動重新部署，不用重做上面的步驟。
- 要換金鑰或邀請碼：到網站右下角「Manage app」→「Settings」→「Secrets」修改後儲存。
- 網站一段時間沒人使用會進入休眠，打開時按「Yes, get this app back up」等一分鐘即可。

## 定時自動喚醒（避免休眠）

專案裡的 `.github/workflows/keep-awake.yml` 會每 6 小時自動打開網站一次（休眠中就自動按喚醒按鈕），並查詢一次 Supabase，避免資料庫因一週沒人用而被暫停。推送到 GitHub 的 **main 分支**後才會開始定時執行。

第一次要在 GitHub 設定（專案頁 → **Settings** → **Secrets and variables** → **Actions**）：

1. **Secrets** 分頁 → New repository secret，新增兩個：
   - `SUPABASE_URL`：和網站 Secrets 裡一樣的 Project URL
   - `SUPABASE_PUBLIC_KEY`：Supabase **Project Settings → API Keys** 裡的 **anon** 或 **publishable** 金鑰（`sb_publishable_` 開頭）。
     這把是公開金鑰，因為資料表有開啟 RLS，用它讀不到任何社團資料；**不要**填 service_role／secret 金鑰。
2. （選用）**Variables** 分頁 → 新增 `APP_URL`，網址有變時填新網址；沒設定就用 `https://club-agent.streamlit.app/`。
3. 到專案頁的 **Actions** → **Keep awake** → **Run workflow** 手動跑一次，看到綠色勾勾就完成了。

注意：GitHub 專案若 **60 天沒有任何 commit**，排程會被自動停用，GitHub 會寄信通知；到 Actions 頁面按「Enable workflow」即可恢復。

## 保護資料與額度

- **邀請碼**（`SIGNUP_CODE`）：建立新社團帳號時必須輸入。沒設定時任何知道網址的人都能建立帳號並使用你的 AI 額度。
- **AI 次數上限**（`MAX_RUNS_PER_SESSION`，預設 20）：每位使用者開啟網頁後最多能執行幾次 AI。
- **財務密碼**：財務資料另外以財務密碼上鎖；目前同一個社團共用一組社團帳號，個人帳號與權限是之後的改進方向。
- **GitHub 專案是公開的**：程式碼任何人都看得到，但金鑰（`secrets.toml`）與社團資料（`data/`）都不會上傳。
- 定期到 Google AI Studio 與 Supabase 查看用量；金鑰外流時立刻在原服務刪除、重新建立，再更新 Secrets。
