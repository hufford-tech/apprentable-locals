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

const RATE_LIMIT_PER_MINUTE = 5;

const json = (body: Record<string, unknown>, status = 200,
              cors: Record<string, string> = corsFor(null)) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });

const htmlEscape = (value: unknown) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const text = (value: unknown, max: number) => String(value ?? "").trim().slice(0, max);

Deno.serve(async (request) => {
  const cors = corsFor(request.headers.get("origin"));
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405, cors);

  let input: Record<string, unknown>;
  try {
    input = await request.json();
  } catch {
    return json({ error: "invalid_json" }, 400, cors);
  }

  const allowedTypes = new Set([
    "Wage data", "Application status", "Requirements", "Contact information",
    "Local match or jurisdiction", "Other",
  ]);
  const report = {
    lu_number: text(input.lu_number, 80),
    local_location: text(input.local_location, 160),
    issue_type: text(input.issue_type, 80),
    message: text(input.message, 5000),
    reporter_email: text(input.reporter_email, 320) || null,
    source_url: text(input.source_url, 2000),
    page_title: text(input.page_title, 300),
    context: input.context && typeof input.context === "object" ? input.context : null,
  };
  if (!report.message || report.message.length < 5) return json({ error: "message_required" }, 400, cors);
  if (!allowedTypes.has(report.issue_type)) return json({ error: "invalid_issue_type" }, 400, cors);
  if (report.reporter_email && !/^\S+@\S+\.\S+$/.test(report.reporter_email)) {
    return json({ error: "invalid_email" }, 400, cors);
  }

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
    body: JSON.stringify({ p_key: `report-issue:${ip}`, p_limit: RATE_LIMIT_PER_MINUTE, p_window_seconds: 60 }),
  });
  const allowed = rlResponse.ok ? await rlResponse.json() : true;
  if (!allowed) return json({ error: "rate_limited" }, 429, cors);

  const insertResponse = await fetch(`${supabaseUrl}/rest/v1/issue_reports`, {
    method: "POST",
    headers: { ...serviceHeaders, Prefer: "return=representation" },
    body: JSON.stringify(report),
  });
  if (!insertResponse.ok) {
    console.error("issue_reports insert failed", insertResponse.status, await insertResponse.text());
    return json({ error: "save_failed" }, 502, cors);
  }
  const inserted = await insertResponse.json();
  const reportId = inserted?.[0]?.id;

  const to = Deno.env.get("REPORT_ISSUE_TO_EMAIL") ?? "hello@apprentable.org";
  const from = Deno.env.get("REPORT_ISSUE_FROM_EMAIL") ?? "reports@apprentable.org";
  const resendKey = Deno.env.get("RESEND_API_KEY");
  let emailSent = false;
  let emailError = "";
  if (to && from && resendKey) {
    const subject = `[IBEW Finder] ${report.issue_type} — ${report.lu_number || "Unspecified local"}`;
    const emailResponse = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${resendKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from,
        to: [to],
        reply_to: report.reporter_email || undefined,
        subject,
        html: `<h2>${htmlEscape(subject)}</h2>
          <p><b>Local:</b> ${htmlEscape(report.lu_number)}</p>
          <p><b>City/state:</b> ${htmlEscape(report.local_location)}</p>
          <p><b>Issue type:</b> ${htmlEscape(report.issue_type)}</p>
          <p><b>Details:</b><br>${htmlEscape(report.message).replaceAll("\n", "<br>")}</p>
          <p><b>Reporter email:</b> ${htmlEscape(report.reporter_email || "Not provided")}</p>
          <p><b>Page:</b> <a href="${htmlEscape(report.source_url)}">${htmlEscape(report.source_url)}</a></p>
          <p><b>Submitted:</b> ${new Date().toISOString()}</p>`,
      }),
    });
    emailSent = emailResponse.ok;
    if (!emailSent) emailError = (await emailResponse.text()).slice(0, 1000);
  } else {
    emailError = "Email secrets are not configured";
  }

  if (reportId) {
    await fetch(`${supabaseUrl}/rest/v1/issue_reports?id=eq.${encodeURIComponent(reportId)}`, {
      method: "PATCH",
      headers: { ...serviceHeaders, Prefer: "return=minimal" },
      body: JSON.stringify({ email_sent: emailSent, email_error: emailSent ? null : emailError }),
    });
  }
  return json({ ok: true, email_sent: emailSent }, 202, cors);
});
