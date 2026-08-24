-- IBEW Apprenticeship Finder: lead capture (email/phone + chosen local).
-- Run once in the Supabase SQL editor (Project -> SQL Editor -> New query)
-- for a fresh project. Safe to re-run: every statement is idempotent.

create table if not exists leads (
  id uuid primary key default gen_random_uuid(),
  lu_number text not null,
  kind text not null check (kind in ('prep', 'alert')),
  email text not null,
  phone text,
  created_at timestamptz not null default now()
);

-- The finder has no auth wired up yet, so this is forward-prep: nullable, and
-- populated client-side only if a Clerk session happens to be present (see
-- capture() in page_template.html). Because inserts go through the public
-- anon key with no server-side check against the actual Clerk JWT, this
-- column is self-reported by the browser, same trust level as email/phone --
-- not something to authorize against without a trigger or edge function that
-- verifies the JWT server-side first.
alter table leads add column if not exists clerk_user_id text;

-- Required the moment alerts actually ship: when consent was given, a token
-- to unsubscribe by (rather than requiring the sender to identify the
-- subscriber some other way), and whether they're still subscribed.
alter table leads add column if not exists consent_at timestamptz;
alter table leads add column if not exists unsubscribe_token uuid not null default gen_random_uuid();
alter table leads add column if not exists subscribed boolean not null default true;

create index if not exists leads_lu_number_idx on leads (lu_number);

alter table leads enable row level security;

-- Direct anonymous insert is revoked -- unrestricted public insert with no
-- server-side validation is how a public domain gets bot-flooded. Lead
-- capture now goes through the capture-lead Edge Function (service role
-- key), which enforces a size cap, email/field validation, a honeypot, and
-- per-IP rate limiting before it ever reaches this table.
drop policy if exists "public can insert leads" on leads;
revoke insert on leads from anon;

-- No public read/update/delete either -- the anon key is embedded in the
-- page source, so anyone could otherwise scrape every visitor's email and
-- phone number straight out of the page's own JS. Query leads from the
-- Supabase dashboard (or with the service role key) instead.
revoke all on leads from anon, authenticated;
