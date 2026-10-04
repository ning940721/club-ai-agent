# Assignment 2

B12702002 曾昱寧

## 一、執行環境與程式語言 (Environment & Language)

- 執行環境：Visual Studio Code (VS Code)
- 作業系統：Windows 11
- 程式語言：Python 3.14.2
- 非原生第三方套件：
  - nltk（只用 `nltk.stem.PorterStemmer` 做詞幹提取，和 PA1 相同）
- 套件安裝指令：
  - `pip install nltk`

tf、df、idf、tf-idf 和 cosine similarity 都是自己寫的，只用 Python 內建的 `math`，沒有用 sklearn 等現成套件。

## 二、執行方式說明 (Execution Steps)

1. **檔案目錄準備**
   把助教提供的 1095 篇新聞文件解壓縮到程式同一層的 `data/` 資料夾，目錄結構如下：

   ```
   B12702002/
   ├── pa2.py
   ├── data/      ← 1.txt ~ 1095.txt
   └── output/    ← 程式自動產生的結果
   ```

2. **環境建置與套件安裝**
   開啟 VS Code 內建終端機 (Terminal) 或 Command Line，執行：
   - `pip install nltk`

3. **程式執行步驟**
   在專案根目錄的 Terminal 輸入：
   - `python pa2.py`

   如果要另外計算任兩篇文件的 cosine similarity（需先跑過上面的指令），輸入：
   - `python pa2.py --cosine 1 2`

4. **執行結果確認與截圖**
   程式跑完後，終端機會印出文件數、字典大小，以及 Document 1 和 Document 2 的 cosine similarity，並在 `./output` 產生：
   - `dictionary.txt`：字典
   - `1.txt` ~ `1095.txt`：每篇文件的 tf-idf 單位向量

   `<在此貼上 Terminal 執行畫面截圖、output 資料夾截圖>`

## 三、作業處理邏輯說明 (Processing Logic)

### 1. 讀取文件 (File Reading)

用 `glob` 讀入 `./data/*.txt` 的所有文件（UTF-8），檔名（不含 .txt）就是 DocID，並依 DocID 數字排序。

### 2. 前處理 (Tokenization，延續 PA1 並改進)

每篇文件依序做以下處理：

1. **轉小寫 (Lowercasing)**：用 `.lower()` 把全文轉成小寫。
2. **處理縮寫與所有格（PA2 新增）**：PA1 直接把撇號換成空白，結果留下 `s`、`t`、`re`、`m` 這類殘留字。PA2 改成先用正則表達式處理：
   - `serbia's` → `serbia`
   - `don't` → `do not`
   - `we're` / `i'm` → `we` / `i`
3. **分詞 (Tokenization)**：用 `re.sub(r'[^a-z\s]', ' ', text)` 把非英文字母換成空白，再用 `.split()` 切成 token。PA2 把數字也一起去掉，避免 `292`、`000` 這類沒有意義的 term 進入字典。
4. **停用詞過濾 (Stopword Removal)**：以 PA1 的停用詞清單為基礎，再加入 PA1 結果中還殘留的高頻無意義詞，例如 `also`、`will`、`just`、`now`、`can`、`may`、`one`、`say`。
5. **詞幹提取 (Stemming)**：用 `nltk.stem.PorterStemmer` 的 `.stem()` 取出字根。
6. **二次過濾（PA2 新增）**：stemming 後如果只剩 1 個字元，或變成停用詞，就丟掉。

以 Document 1 為例，PA1 抽出 183 個 terms，PA2 改進後是 155 個，殘留的停用詞和數字都去掉了。

### 3. 建立字典與 Document Frequency

- 對每篇文件計算 **term frequency**：`tf(t, d)` = term t 在文件 d 中出現的次數（用 dict 計數）。
- 計算 **document frequency**：`df(t)` = 含有 term t 的文件數，同一篇文件出現多次只算一次。
- 所有 term 依字母**升冪排序**，`t_index` 從 1 開始編號，輸出 `dictionary.txt`：

  ```
  t_index	term	df
  1	aaa	1
  2	abandon	5
  ...
  ```

### 4. 計算 tf-idf 單位向量

- `idf(t) = log10(N / df(t))`，N 為文件總數（1095）。
- `tf-idf(t, d) = tf(t, d) × idf(t)`
- 每篇文件的向量除以自己的長度 `sqrt(Σ tf-idf²)`，變成單位向量 (unit vector)。
- 輸出 `./output/DocID.txt`：第一行是這篇文件的 term 數，第二行是表頭，之後每行是 `t_index` 和 tf-idf 值，依 t_index 排序：

  ```
  119
  t_index	tf-idf
  1	...
  ...
  ```

### 5. Cosine Similarity

`cosine(Docx, Docy)` 會讀入 `./output/x.txt` 和 `./output/y.txt`，把兩個向量存成 `{t_index: tf-idf}` 的 dict，對共同的 t_index 算內積，再除以兩個向量長度的乘積：

cos(x, y) = (x · y) / (‖x‖ × ‖y‖)

## 四、結果 (Result)

- 文件數：1095
- 字典大小：`<程式印出的 Dictionary size>` 個 terms
- **Document 1 與 Document 2 的 cosine similarity = `<程式印出的數值>`**
