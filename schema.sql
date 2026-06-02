-- ============================================================
--  Quality Command Centre — Supabase schema
--  Run this once in: Supabase Dashboard → SQL Editor → New query
-- ============================================================

create table if not exists public.records (
  id          uuid           primary key default gen_random_uuid(),
  category    text           not null,
  serial_no   integer,
  data        jsonb          not null default '{}'::jsonb,
  created_at  timestamptz    not null default now()
);

-- Fast filtering by category (the app always lists per-category)
create index if not exists records_category_idx on public.records (category);
create index if not exists records_created_idx  on public.records (created_at desc);

-- ------------------------------------------------------------
--  Row-Level Security
--  Because the Flask backend uses the SERVICE-ROLE key, it
--  bypasses RLS entirely. We still ENABLE RLS so that the
--  public anon key (if ever exposed) gets ZERO access by default.
-- ------------------------------------------------------------
alter table public.records enable row level security;

-- No policies are created on purpose.
-- => anon/public key  : cannot read or write anything (RLS denies all)
-- => service-role key : full access (used only by your Flask server)
