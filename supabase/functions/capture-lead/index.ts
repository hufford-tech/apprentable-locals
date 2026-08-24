// Public lead capture (email/phone + chosen local). Replaces direct anonymous
// insert into `leads` (revoked in leads_schema.sql) -- this is the only path
// onto that table now, so it's also the only place that has to enforce a
// size cap, field validation, a honeypot, and per-IP rate limiting.

// Origins allowed to call this function. Set ALLOWED_ORIGINS (comma-separated)
// in the function's environment to add a Vercel test deployment or a preview
// URL without editing code. Defaults cover the live site with and without www.
const ALLOWED_ORIGINS = (Deno.env.get("ALLOWED_ORIGINS") ??
  "https://apprentable.org,https://www.apprentable.org")
  .split(",").map((s) => s.trim()).filter(Boolean);

const corsFor = (origin: string | null) => ({
  "Access-Control-Allow-Origin":
    origin && ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
  "Vary": "Origin",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
});

const json = (body: Record<string, unknown>, status = 200,
              cors: Record<string, string> = corsFor(null)) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });

const text = (value: unknown, max: number) => String(value ?? "").trim().slice(0, max);

const MAX_BODY_BYTES = 4096;
const RATE_LIMIT_PER_MINUTE = 5;

Deno.serve(async (request) => {
  const cors = corsFor(request.headers.get("origin"));
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405, cors);

  const contentLength = Number(request.headers.get("content-length") || "0");
  if (contentLength > MAX_BODY_BYTES) return json({ error: "payload_too_large" }, 413, cors);

  const rawBody = await request.text();
  if (rawBody.length > MAX_BODY_BYTES) return json({ error: "payload_too_large" }, 413, cors);

  let input: Record<string, unknown>;
  try {
    input = JSON.parse(rawBody);
  } catch {
    return json({ error: "invalid_json" }, 400, cors);
  }

  // Honeypot: a hidden field real users never see or fill. A bot filling
  // every input on the form fills this too -- discard silently (200-ish
  // success response) so the bot has no signal to adapt on.
  if (text(input.website, 200)) return json({ ok: true }, 202, cors);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceKey) return json({ error: "server_not_configured" }, 500, cors);
  const serviceHeaders = {
    "Content-Type": "application/json",
    apikey: serviceKey,
    Authorization: `Bearer ${serviceKey}`,
  };

  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
  const rlResponse = await fetch(`${supabaseUrl}/rest/v1/rpc/check_rate_limit`, {
    method: "POST",
    headers: serviceHeaders,
    body: JSON.stringify({ p_key: `capture-lead:${ip}`, p_limit: RATE_LIMIT_PER_MINUTE, p_window_seconds: 60 }),
  });
  const allowed = rlResponse.ok ? await rlResponse.json() : true;
  if (!allowed) return json({ error: "rate_limited" }, 429, cors);

  const lu_number = text(input.lu_number, 20);
  const kind = text(input.kind, 20);
  const email = text(input.email, 320);
  const phone = text(input.phone, 40) || null;
  const clerk_user_id = text(input.clerk_user_id, 200) || null;

  if (!lu_number) return json({ error: "lu_number_required" }, 400, cors);
  if (!["prep", "alert"].includes(kind)) return json({ error: "invalid_kind" }, 400, cors);
  if (!/^\S+@\S+\.\S+$/.test(email)) return json({ error: "invalid_email" }, 400, cors);
  if (phone && !/^[0-9()+\-.\s]{7,20}$/.test(phone)) return json({ error: "invalid_phone" }, 400, cors);

  const insertResponse = await fetch(`${supabaseUrl}/rest/v1/leads`, {
    method: "POST",
    headers: { ...serviceHeaders, Prefer: "return=minimal" },
    body: JSON.stringify({
      lu_number, kind, email, phone, clerk_user_id,
      consent_at: new Date().toISOString(),
    }),
  });
  if (!insertResponse.ok) {
    console.error("leads insert failed", insertResponse.status, await insertResponse.text());
    return json({ error: "save_failed" }, 502, cors);
  }
  return json({ ok: true }, 202, cors);
});
