"""測試用的假 Supabase 用戶端：只實作 SupabaseClubStore 用到的查詢方法，並模擬主鍵與 unique 限制。"""

from __future__ import annotations

import copy

KEYS = {"clubs": ("club_id",), "club_docs": ("club_id", "collection", "doc_id"), "club_records": ("id",)}
UNIQUE = {"clubs": (("account",),)}


class FakeAPIError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db: FakeClient, table: str):
        self.db, self.table = db, table
        self.op, self.payload, self.columns = "select", None, None
        self.filters: list[tuple[str, object]] = []
        self.orders: list[tuple[str, bool]] = []
        self.window: tuple[int, int] | None = None
        self.max_rows: int | None = None
        self.conflict: tuple[str, ...] = ()

    def select(self, columns="*"):
        self.op, self.columns = "select", None if columns == "*" else [c.strip() for c in columns.split(",")]
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def upsert(self, row, on_conflict=""):
        self.op, self.payload, self.conflict = "upsert", row, tuple(c.strip() for c in on_conflict.split(",") if c)
        return self

    def update(self, data):
        self.op, self.payload = "update", data
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False):
        self.orders.append((column, desc))
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def limit(self, n):
        self.max_rows = n
        return self

    def _match(self, row):
        return all(row.get(c) == v for c, v in self.filters)

    def execute(self):
        self.db.calls += 1
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "select":
            out = [r for r in rows if self._match(r)]
            for column, desc in reversed(self.orders):
                out.sort(key=lambda r: r[column], reverse=desc)
            if self.window:
                out = out[self.window[0]: self.window[1] + 1]
            if self.max_rows is not None:
                out = out[: self.max_rows]
            if self.columns:
                out = [{c: r[c] for c in self.columns} for r in out]
            return _Result(copy.deepcopy(out))
        if self.op == "insert":
            row = copy.deepcopy(self.payload)
            self._check_unique(row, rows)
            rows.append(row)
            return _Result([row])
        if self.op == "upsert":
            row = copy.deepcopy(self.payload)
            key = self.conflict or KEYS[self.table]
            for i, r in enumerate(rows):
                if all(r.get(k) == row.get(k) for k in key):
                    rows[i] = {**r, **row}
                    return _Result([rows[i]])
            rows.append(row)
            return _Result([row])
        if self.op == "update":
            for r in rows:
                if self._match(r):
                    r.update(copy.deepcopy(self.payload))
            return _Result([])
        if self.op == "delete":
            self.db.tables[self.table] = [r for r in rows if not self._match(r)]
            return _Result([])
        raise AssertionError(self.op)

    def _check_unique(self, row, rows):
        for columns in (KEYS[self.table], *UNIQUE.get(self.table, ())):
            if any(all(r.get(c) == row.get(c) for c in columns) for r in rows):
                raise FakeAPIError("23505", f"duplicate key value violates unique constraint on {columns}")


class FakeClient:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.calls = 0

    def table(self, name):
        return _Query(self, name)
