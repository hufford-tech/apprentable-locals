-- Shared per-IP rate limiting for public Edge Functions (capture-lead,
-- report-issue). Run once in the Supabase SQL editor. Safe to re-run.

create table if not exists rate_limits (
  key text primary key,
  window_start timestamptz not null,
  count int not null default 0
);

-- Atomic fixed-window counter: bumps the count if the window is still open,
-- resets it if the window has expired. Must be a single statement (not a
-- read-then-write from the Edge Function) or concurrent requests from the
-- same IP would race past the limit.
create or replace function check_rate_limit(p_key text, p_limit int, p_window_seconds int)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count int;
  v_now timestamptz := now();
begin
  insert into rate_limits (key, window_start, count)
  values (p_key, v_now, 1)
  on conflict (key) do update set
    count = case
      when rate_limits.window_start < v_now - make_interval(secs => p_window_seconds) then 1
      else rate_limits.count + 1
    end,
    window_start = case
      when rate_limits.window_start < v_now - make_interval(secs => p_window_seconds) then v_now
      else rate_limits.window_start
    end
  returning count into v_count;
  return v_count <= p_limit;
end;
$$;

-- Only the Edge Functions (via the service role key) call this -- never the
-- public anon key directly, or a bot could just call it to probe/reset limits.
revoke all on function check_rate_limit(text, int, int) from public, anon, authenticated;
grant execute on function check_rate_limit(text, int, int) to service_role;

alter table rate_limits enable row level security;
revoke all on rate_limits from anon, authenticated;
