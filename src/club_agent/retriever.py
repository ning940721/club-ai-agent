"""知識庫檢索（RAG 的 Retrieval 部分）。

預設實作為零外部依賴的 BM25 檢索器，以「中文字元二元組 + 英數詞」斷詞，
對繁體中文短文件效果穩定，且不需額外的 embedding 服務即可運作。

`Retriever` 為抽象介面，之後若要換成向量資料庫（如 LangChain / LlamaIndex +
Chroma / FAISS），只要實作同樣的 `search()` 即可替換，Agent 程式碼不需修改。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_KB_DIR = Path(__file__).parent / "knowledge_base"

_CJK = re.compile(r"[一-鿿]+")
_WORD = re.compile(r"[a-zA-Z0-9#@]+")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens: list[str] = _WORD.findall(text)
    for run in _CJK.findall(text):
        if len(run) == 1:
            tokens.append(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


@dataclass
class Chunk:
    source: str
    heading: str
    text: str

    def render(self) -> str:
        return f"【{self.source}｜{self.heading}】\n{self.text.strip()}"


class Retriever(Protocol):
    def search(self, query: str, k: int = 4) -> list[Chunk]: ...


def split_markdown(source: str, content: str) -> list[Chunk]:
    """依二、三級標題切塊，讓每個 chunk 聚焦單一主題。"""
    chunks: list[Chunk] = []
    doc_title = source
    heading, buf = "", []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            chunks.append(Chunk(source, heading or doc_title, body))

    for line in content.splitlines():
        if line.startswith("# "):
            doc_title = line[2:].strip()
        elif line.startswith("## ") or line.startswith("### "):
            flush()
            heading, buf = line.lstrip("#").strip(), []
        else:
            buf.append(line)
    flush()
    return chunks


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        if not chunks:
            raise ValueError("知識庫是空的")
        self.chunks = chunks
        self.k1, self.b = k1, b
        self._docs = [Counter(tokenize(f"{c.heading} {c.text}")) for c in chunks]
        self._lens = [sum(d.values()) for d in self._docs]
        self._avglen = sum(self._lens) / len(self._lens)
        df: Counter[str] = Counter()
        for d in self._docs:
            df.update(d.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def from_directory(cls, directory: str | Path = DEFAULT_KB_DIR) -> BM25Retriever:
        chunks: list[Chunk] = []
        for path in sorted(Path(directory).glob("*.md")):
            chunks.extend(split_markdown(path.name, path.read_text(encoding="utf-8")))
        return cls(chunks)

    def score(self, query: str, idx: int) -> float:
        doc, dl = self._docs[idx], self._lens[idx]
        s = 0.0
        for t in set(tokenize(query)):
            tf = doc.get(t)
            if not tf:
                continue
            norm = tf + self.k1 * (1 - self.b + self.b * dl / self._avglen)
            s += self._idf[t] * tf * (self.k1 + 1) / norm
        return s

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        scored = [(self.score(query, i), i) for i in range(len(self.chunks))]
        scored = [x for x in scored if x[0] > 0]
        scored.sort(reverse=True)
        return [self.chunks[i] for _, i in scored[:k]]


def format_context(chunks: list[Chunk]) -> str:
    if not chunks:
        return "（知識庫中沒有找到相關資料）"
    return "\n\n".join(c.render() for c in chunks)
