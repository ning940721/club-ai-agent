# IRTM Programming Assignment 2 Report

學號：`<請填寫>`　姓名：`<請填寫>`

## 1. 執行環境

- 執行環境：命令列（Terminal / cmd），任何 Python 3 IDE（如 PyCharm、VS Code）亦可
- 作業系統：`<例：Windows 11 / macOS 15 / Ubuntu 24.04>`
- 程式語言：Python `<請填 python --version 的結果，例如 3.11.x>`（需 Python 3 以上）

## 2. 使用套件

只用 Python 內建模組（`re`、`math`、`glob`、`os`、`argparse`），**不需要 pip install 任何套件**。
Porter stemmer 和英文 stopword list 都直接寫在 `pa2.py` 裡，所以也不需要 `nltk` 或額外的 `stopwords.txt`。

## 3. 執行方式

1. 把助教提供的 1095 篇文件解壓縮到程式同一層的 `data/` 資料夾，也就是 `./data/1.txt` ~ `./data/1095.txt`。
2. 在 `pa2.py` 所在的資料夾開啟終端機，執行：

   ```bash
   python pa2.py
   ```

3. 程式會產生：
   - `./output/dictionary.txt`：字典（依 term 字母順序排序，含 t_index、term、df）
   - `./output/1.txt` ~ `./output/1095.txt`：每篇文件的 tf-idf 單位向量
   - 並在螢幕上印出 `cosine(Doc1, Doc2)`
4. 若要另外計算任兩篇文件的 cosine similarity（需先執行過步驟 2）：

   ```bash
   python pa2.py --cosine 1 2
   ```

`<請在此附上執行步驟 2 的終端機截圖，以及 output 資料夾內容的截圖>`

## 4. 作業處理邏輯

### 4.1 Tokenization（沿用 PA1）

每篇文件依序做以下處理：

1. **Lowercasing**：全部轉成小寫。
2. **去除所有格與撇號**：`'s` 刪除（`reagan's` → `reagan`），其他撇號直接移除（`don't` → `dont`）。
3. **去除標點符號與數字**：非英文字母的字元全部換成空白，再依空白切出 token。
4. **移除 stopwords**：使用內建的英文 stopword list（以 NLTK / SMART 的清單為基礎）。
5. **Porter stemming**：自己實作 Porter (1980) 演算法，並與 NLTK `PorterStemmer(ORIGINAL_ALGORITHM)` 比對過結果。
6. **再過濾一次**：stemming 後若變成 stopword，或只剩 1 個字元，就丟掉。

### 4.2 建立字典與 df

- 每篇文件把 token 數成 term frequency：`tf(t, d)` = term t 在文件 d 中出現的次數。
- `df(t)` = 含有 term t 的文件數（同一篇出現多次只算一次）。
- 所有 term 依字母**升冪排序**，`t_index` 從 1 開始編號，寫成 `dictionary.txt`：

  ```
  t_index	term	df
  1	aaa	3
  2	abandon	12
  ...
  ```

### 4.3 tf-idf 單位向量

- `idf(t) = log10(N / df(t))`，其中 N = 文件總數（1095）。
- `w(t, d) = tf(t, d) × idf(t)`
- 把每篇文件的向量除以自己的 L2 norm `sqrt(Σ w²)`，變成單位向量。
- 輸出 `DocID.txt`：第一行是這篇文件有幾個 term，第二行是表頭，接著每行是 `t_index` 和 tf-idf 值（依 t_index 排序）。

tf、df、idf、tf-idf 全部是自己寫的，沒有用 sklearn 之類的套件。

### 4.4 Cosine similarity

`cosine(Docx, Docy)` 會讀入 `./output/x.txt` 和 `./output/y.txt` 兩個向量檔，存成 `{t_index: weight}` 的稀疏 dict，計算

cos(x, y) = (x · y) / (‖x‖ ‖y‖)

因為兩個向量都已經是單位向量，結果其實就等於內積；這裡仍然除以 norm，讓函式也能用在沒有正規化的向量上。

## 5. 結果

- 字典大小：`<程式印出的 Dictionary size>` 個 terms
- **Document 1 與 Document 2 的 cosine similarity：`<程式印出的 cosine(Doc1, Doc2)>`**
