# 網頁版上線教學（Streamlit Community Cloud，免費）

上線後會得到一個網址（例如 `https://xxx.streamlit.app`），社團幹部用手機或電腦打開、輸入密碼就能使用。
你的 Gemini 金鑰只存在 Streamlit 的後台，使用者看不到。

## 一、先在自己電腦試跑

```bash
git pull
pip install -r requirements.txt
```

把 `.streamlit/secrets.toml.example` 複製一份，改名為 `.streamlit/secrets.toml`，填入你的金鑰與自訂密碼
（這個檔案已設定不會上傳到 GitHub）。然後執行：

```bash
streamlit run app.py
```

瀏覽器會自動打開 `http://localhost:8501`。

## 二、部署到網路上

1. 到 **share.streamlit.io**，用你的 GitHub 帳號登入，並同意授權存取 `club-ai-agent` 專案。
2. 按「Create app」（或「New app」）→ 選擇從 GitHub 部署，填入：
   - Repository：`ning940721/club-ai-agent`
   - Branch：`claude/planning-document-creation-76lhic`（合併到 main 之後改成 `main`）
   - Main file path：`app.py`
3. 展開「Advanced settings」：
   - Python version 選 3.11 或以上
   - **Secrets** 欄位貼上（換成你的金鑰與密碼）：
     ```toml
     GEMINI_API_KEY = "你的 Gemini 金鑰"
     APP_PASSWORD = "給幹部的使用密碼"
     ```
4. 按「Deploy」，等幾分鐘安裝完成，就會得到網址。

> 介面文字可能隨 Streamlit 更新而略有不同，找對應的選項即可。
> 若專案是私人（private）儲存庫，免費方案可部署的數量可能有限制，請以 Streamlit 官網說明為準。

## 三、之後怎麼更新

程式推送到 GitHub 的同一個分支後，Streamlit 會自動重新部署，不用重做上面的步驟。
要換金鑰或密碼：到 App 的「Settings → Secrets」修改後儲存。

## 保護你的額度

- **使用密碼**（`APP_PASSWORD`）：只把密碼給參與實測的社團幹部。沒設定時任何知道網址的人都能使用。
- **次數上限**（`MAX_RUNS_PER_SESSION`，預設 20）：每位使用者開啟網頁後最多能執行幾次 AI 分析。
- 定期到 Google AI Studio 查看用量；發現異常時立刻在 AI Studio 刪除舊金鑰、建立新金鑰，再更新 Secrets。
