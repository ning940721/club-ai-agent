from club_agent.retriever import BM25Retriever, Chunk, split_markdown, tokenize


def test_tokenize_mixed():
    toks = tokenize("IG 互動率 Reels")
    assert "ig" in toks and "reels" in toks
    assert "互動" in toks and "動率" in toks


def test_split_markdown():
    chunks = split_markdown("a.md", "# 標題\n前言\n## 第一節\n內容一\n### 小節\n內容二\n")
    assert [c.heading for c in chunks] == ["標題", "第一節", "小節"]


def test_bm25_ranks_relevant_first():
    r = BM25Retriever([Chunk("a", "發文時間", "晚上八點到十一點是大學生上線高峰"), Chunk("b", "預算", "印刷與抽獎禮品費用")])
    assert r.search("什麼時間發文比較好", k=1)[0].source == "a"
    assert r.search("完全無關的字詞qqq") == []


def test_builtin_knowledge_base_loads():
    r = BM25Retriever.from_directory()
    hits = r.search("週年大成 宣傳時程", k=3)
    assert any("時程" in h.source or "時程" in h.heading for h in hits)
