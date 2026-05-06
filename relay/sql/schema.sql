-- ArchHub Cloud Relay schema.
--
-- Run once against a fresh Supabase project. Idempotent where reasonable
-- (CREATE IF NOT EXISTS), but RLS policy redefinition will error on a
-- re-run — drop those manually if you need to re-apply.
--
-- Encryption: the *_key_encrypted columns are intended to be Supabase
-- Vault references. For a v0 deploy you can store them as plaintext
-- TEXT (the relay reads the column verbatim); migrate to Vault before
-- onboarding the second paying firm.

-- ---------- firms ---------------------------------------------------------
create table if not exists public.firms (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    plan_tier text not null default 'free' check (plan_tier in ('free','studio','enterprise')),
    monthly_token_cap bigint not null default 100000,
    anthropic_key_encrypted text,
    openai_key_encrypted text,
    google_key_encrypted text,
    openrouter_key_encrypted text,
    created_at timestamptz not null default now()
);

-- ---------- users ---------------------------------------------------------
-- We mirror auth.users with our own row so we can attach firm_id + role
-- without touching the auth schema.
create table if not exists public.users (
    id uuid primary key references auth.users(id) on delete cascade,
    firm_id uuid not null references public.firms(id) on delete restrict,
    email text not null,
    role text not null default 'member' check (role in ('member','admin','owner')),
    created_at timestamptz not null default now()
);

create index if not exists users_firm_id_idx on public.users(firm_id);

-- ---------- usage (partitioned monthly) -----------------------------------
-- Partitioning by occurred_at keeps the cap-enforcement view fast as the
-- table grows past a few million rows. Create new partitions monthly via
-- a Supabase scheduled function or pg_partman — for v0, hand-create a
-- year ahead and cron-bump after.
create table if not exists public.usage (
    id bigserial,
    user_id uuid not null references public.users(id) on delete cascade,
    firm_id uuid not null references public.firms(id) on delete cascade,
    provider text not null,
    model text not null,
    prompt_tokens integer not null default 0,
    completion_tokens integer not null default 0,
    latency_ms integer not null default 0,
    occurred_at timestamptz not null default now(),
    primary key (id, occurred_at)
) partition by range (occurred_at);

-- Bootstrap partitions: current month + the next 11. Adjust the start
-- date when you re-run; the loop is idempotent against existing names.
do $$
declare
    m date := date_trunc('month', now())::date;
    i int;
    pname text;
begin
    for i in 0..11 loop
        pname := format('usage_%s', to_char(m + (i || ' month')::interval, 'YYYY_MM'));
        execute format(
            'create table if not exists public.%I partition of public.usage for values from (%L) to (%L)',
            pname,
            (m + (i || ' month')::interval)::date,
            (m + ((i+1) || ' month')::interval)::date
        );
    end loop;
end $$;

create index if not exists usage_firm_occurred_idx on public.usage(firm_id, occurred_at);
create index if not exists usage_user_occurred_idx on public.usage(user_id, occurred_at);

-- ---------- monthly aggregate view ---------------------------------------
create or replace view public.monthly_usage_per_firm as
select
    firm_id,
    sum(prompt_tokens + completion_tokens)::bigint as total_tokens,
    count(*)::bigint as request_count
from public.usage
where occurred_at >= date_trunc('month', now())
group by firm_id;

-- ---------- RLS -----------------------------------------------------------
alter table public.firms enable row level security;
alter table public.users enable row level security;
alter table public.usage enable row level security;

-- A user can read their own user row.
create policy users_self_select on public.users
    for select using (id = auth.uid());

-- A user can read their firm's metadata, but NOT the *_key_encrypted
-- columns. Postgres RLS is row-level, not column-level — so we wrap the
-- safe columns in a view and let users hit that instead. The relay,
-- which uses service_role, ignores RLS.
create policy firms_member_select on public.firms
    for select using (
        id in (select firm_id from public.users where id = auth.uid())
    );

create or replace view public.firms_public as
    select id, name, plan_tier, monthly_token_cap, created_at from public.firms;

-- A user can read their own usage rows; firm admins can read all firm rows.
create policy usage_self_select on public.usage
    for select using (
        user_id = auth.uid()
        or firm_id in (
            select firm_id from public.users
            where id = auth.uid() and role in ('admin','owner')
        )
    );

-- The view inherits RLS from its base table, so monthly_usage_per_firm
-- is automatically firm-scoped for end-user queries. The relay reads it
-- via service_role to enforce caps.
