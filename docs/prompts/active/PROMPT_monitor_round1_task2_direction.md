# Monitor round 1: direction for tasks 2 through 5

Continue `PROMPT_monitor_round1.md`. Same ownership and constraints. Task 1's noise audit
is accepted; 24.7% over ten minutes, and 52 of the 54 unstable URLs sit inside the 99
flagged at 26 hours, so at least 52 of those 99 were never real changes.

## The key observation in your own categories

Read your table again by *where* the churn lives, not what it is:

- ASP.NET `__VIEWSTATE`, CSRF tokens, nonces, form-build IDs — **HTML attributes**
- cache-busting `?ver=`, `?wpr_t=` — **attribute values in asset URLs**
- Cloudflare email obfuscation — **a `data-cfemail` attribute**
- AWS S3 presigned params, `x-amz-date` — **attribute values in URLs**
- Google Sites CDN thumbnail hash (LU 613 Atlanta) — **an `img src` attribute**
- slider instance IDs, random DOM IDs, `devicetype=other` feature flags — **attributes**

That is roughly 33 of your 54, and none of it is content a visitor reads. Only four
categories are actually visible text: the tradeschoolinc arithmetic captcha, hit counters,
"generated N seconds ago", and possibly LU 80.

**So the primary rule is: hash visible text only, and discard every HTML attribute.** Do
that before writing a single token-specific regex. One structural change removes most of
the noise, and it will not rot the way a list of per-vendor patterns would.

## Task 2, revised

1. **Extract visible text.** Drop `<script>`, `<style>`, `<noscript>`, comments, and
   `<head>` entirely. Then take text nodes only, discarding all tags and all attributes.
   Collapse whitespace, lowercase, hash.
2. Then, on the extracted text only, redact:
   - date and time shapes: ISO dates, `M/D/YYYY`, `Month D, YYYY`, `HH:MM`, day names.
     Leave bare four-digit years alone unless adjacent to a date word — "2026 Program" is
     real content and matters for status.
   - standalone runs of 5+ digits (counters, IDs)
   - `generated \d+ seconds? ago` and similar batcache stamps
3. **One targeted rule, because it is visible text and appears on seven locals:** the
   tradeschoolinc arithmetic captcha, shaped like `X + Y =`. Redact the operands. Note in
   a comment that this is vendor-specific and why a general rule cannot catch it.
4. Do **not** try to isolate a main content region. Attribute stripping should do most of
   the work, and region detection across 219 hand-built sites is a rabbit hole. If the
   false-positive rate is still high after step 1 to 3, then report that and we will
   reconsider.
5. Keep `last_hash_legacy` alongside the new hash.

## The test that matters most

Before reporting a false-positive rate, prove the normaliser is not simply erasing
everything. Required tests:

- two documents differing only in `__VIEWSTATE`, a `?ver=` parameter, a `data-cfemail`
  value, an S3 presigned URL, a hit counter, and a captcha pair → **same hash**
- two documents differing in one real sentence, "Applications are now open" versus
  "Applications are closed" → **different hash**
- two documents differing only in `2026 Program` versus `2027 Program` → **different
  hash**. A normaliser that eats program years would hide exactly the changes we care
  about.

A perfect 0% false-positive rate with a broken third test is worthless.

## Tasks 3 through 5

Unchanged from the original prompt: candidate-then-confirmed change detection with
`pending_hash` and `pending_since`, `out/monitor_flapping.csv`, re-baseline, then the
ten-minute double sweep again.

Bar is still under 5%. Report where it lands honestly. A known 12% with the offenders
named beats an unexplained 5%.

Then give me your yes or no on scheduling it daily, and settle the open question from task
1: of the 47 flagged at 26 hours that the ten-minute test could not classify, how many
survive the new normaliser? That number is the real answer to "do these sites ever
actually change."

## LU 80

You flagged it as genuinely ambiguous, a structural `<link>` change rather than a token.
Once the normaliser is in, check it again. If it still differs, look at whether the
visible text changed at all. If the text is identical, it was markup churn and the new
approach handles it. Report either way.
