-- Data-issue reports submitted from the public finder.
-- The browser calls the report-issue Edge Function; it does not receive
-- direct insert access to this table.

create table if not exists issue_reports (
  id uuid primary key default gen_random_uuid(),
  lu_number text not null default '',
  local_location text not null default '',
  issue_type text not null default 'Other'
    check (issue_type in ('Wage data', 'Application status', 'Requirements',
                          'Contact information', 'Local match or jurisdiction', 'Other')),
  message text not null check (char_length(message) between 5 and 5000),
  reporter_email text,
  source_url text not null default '',
  page_title text not null default '',
  context jsonb,
  email_sent boolean not null default false,
  email_error text,
  status text not null default 'new' check (status in ('new', 'reviewing', 'resolved')),
  created_at timestamptz not null default now()
);

create index if not exists issue_reports_created_at_idx on issue_reports (created_at desc);
create index if not exists issue_reports_lu_number_idx on issue_reports (lu_number);

alter table issue_reports enable row level security;

-- No public table access. The Edge Function uses the service role key after
-- validating the request and is the only writer.
revoke all on issue_reports from anon, authenticated;
