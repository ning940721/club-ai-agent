-- 社團營運平台的線上資料庫（Supabase）。
-- 使用方式：Supabase 專案 → 左側 SQL Editor → New query → 貼上全部內容 → Run。
-- 重複執行也沒關係（已經存在的資料表不會被刪除）。

-- 社團帳號（密碼只存雜湊）
create table if not exists clubs (
  club_id text primary key,
  account text not null unique,
  data jsonb not null,
  created_at timestamptz not null default now()
);

-- 各種資料集合：待辦、會議記錄、報帳、活動專案、行事曆…
create table if not exists club_docs (
  club_id text not null references clubs(club_id) on delete cascade,
  collection text not null,
  doc_id text not null,
  data jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (club_id, collection, doc_id)
);

-- 各部門分享的成果
create table if not exists club_records (
  id text primary key,
  club_id text not null references clubs(club_id) on delete cascade,
  department text not null,
  created_at text not null,
  data jsonb not null
);
create index if not exists club_records_club_created on club_records (club_id, created_at desc);

-- 開啟 Row Level Security 且不設任何規則：只有網站主機上的 service_role 金鑰能讀寫，
-- 就算有人拿到專案的公開（anon）金鑰也讀不到資料。
alter table clubs enable row level security;
alter table club_docs enable row level security;
alter table club_records enable row level security;
