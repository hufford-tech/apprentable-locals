// node --test test_finder_core.js
// Frontend task 10: unit tests for the pure search/status logic extracted
// into site/js/finder-core.js.
const test = require("node:test");
const assert = require("node:assert/strict");
const FC = require("./site/js/finder-core.js");

test("normalizeZip: empty input", () => {
  assert.deepEqual(FC.normalizeZip(""), { kind: "empty" });
  assert.deepEqual(FC.normalizeZip("   "), { kind: "empty" });
});

test("normalizeZip: sub-5-digit input (3-4 digits) is still typing", () => {
  // matches page_template.html's original /^\d{3,5}$/: 1-2 digits aren't
  // even recognized as a ZIP attempt yet, they fall through to city search.
  assert.deepEqual(FC.normalizeZip("021"), { kind: "zip_incomplete" });
  assert.deepEqual(FC.normalizeZip("0213"), { kind: "zip_incomplete" });
});

test("normalizeZip: 1-2 digit input doesn't match the ZIP pattern yet, treated as a city query", () => {
  assert.deepEqual(FC.normalizeZip("0"), { kind: "city", needle: "0" });
  assert.deepEqual(FC.normalizeZip("02"), { kind: "city", needle: "02" });
});

test("normalizeZip: zero-padding for < 5 leading-zero ZIPs typed without the zero", () => {
  // a user typing a leading-zero ZIP one digit short of 5 is still "incomplete"
  // (matches the original page_template.html behavior: length<5 => keep typing)
  assert.deepEqual(FC.normalizeZip("2138"), { kind: "zip_incomplete" });
  // once they've typed all 5 digits (with the leading zero) it pads to a no-op
  assert.deepEqual(FC.normalizeZip("02138"), { kind: "zip", zip5: "02138" });
});

test("normalizeZip: complete 5-digit ZIP", () => {
  assert.deepEqual(FC.normalizeZip("94110"), { kind: "zip", zip5: "94110" });
  assert.deepEqual(FC.normalizeZip("  75201  "), { kind: "zip", zip5: "75201" });
});

test("normalizeZip: unknown ZIP still classifies as a zip (lookup is the caller's job)", () => {
  assert.deepEqual(FC.normalizeZip("99999"), { kind: "zip", zip5: "99999" });
});

test("normalizeZip: non-numeric input classifies as a city query", () => {
  assert.deepEqual(FC.normalizeZip("Boston"), { kind: "city", needle: "boston" });
  assert.deepEqual(FC.normalizeZip("New York, NY"), { kind: "city", needle: "new york, ny" });
});

test("matchCities: prefix match, case-insensitive", () => {
  const keys = ["Boston, MA", "Bothell, WA", "Worcester, MA", "boise, ID"];
  assert.deepEqual(FC.matchCities(keys, "bo"), ["Boston, MA", "Bothell, WA", "boise, ID"]);
});

test("matchCities: no match returns empty array", () => {
  const keys = ["Boston, MA", "Worcester, MA"];
  assert.deepEqual(FC.matchCities(keys, "zzz"), []);
});

test("matchCities: respects the limit", () => {
  const keys = ["Aa, X", "Ab, X", "Ac, X", "Ad, X"];
  assert.equal(FC.matchCities(keys, "a", 2).length, 2);
});

test("unionCityIndexes: unions and de-duplicates, sorted ascending", () => {
  const cityIndex = { "Boston, MA": [3, 1], "Bothell, WA": [1, 2] };
  assert.deepEqual(FC.unionCityIndexes(cityIndex, ["Boston, MA", "Bothell, WA"]), [1, 2, 3]);
});

test("unionCityIndexes: missing key is tolerated", () => {
  const cityIndex = { "Boston, MA": [0] };
  assert.deepEqual(FC.unionCityIndexes(cityIndex, ["Boston, MA", "Nowhere, ZZ"]), [0]);
});

test("statusLabel: every known status has a label", () => {
  for (const status of ["open", "rolling", "closed_pending", "closed", "expired_data", "conflicting", "unknown"]) {
    assert.equal(typeof FC.statusLabel(status), "string");
    assert.ok(FC.statusLabel(status).length > 0);
  }
});

test("statusLabel: unrecognized status falls back to the unknown label", () => {
  assert.equal(FC.statusLabel("bogus_status"), FC.LABEL.unknown);
  assert.equal(FC.statusLabel(undefined), FC.LABEL.unknown);
});

test("statusNote: every known status has a note, unrecognized falls back", () => {
  for (const status of Object.keys(FC.NOTE)) {
    assert.ok(FC.statusNote(status).length > 0);
  }
  assert.equal(FC.statusNote("bogus_status"), FC.NOTE.unknown);
});

test("confidenceLabel: maps short codes, falls back to em dash", () => {
  assert.equal(FC.confidenceLabel("h"), "high");
  assert.equal(FC.confidenceLabel("m"), "medium");
  assert.equal(FC.confidenceLabel("l"), "low");
  assert.equal(FC.confidenceLabel(""), "—");
  assert.equal(FC.confidenceLabel(undefined), "—");
});

test("isConfirmedStatus: open/rolling/closed_pending/closed are confirmed", () => {
  assert.ok(FC.isConfirmedStatus("open"));
  assert.ok(FC.isConfirmedStatus("rolling"));
  assert.ok(FC.isConfirmedStatus("closed_pending"));
  assert.ok(FC.isConfirmedStatus("closed"));
});

test("isConfirmedStatus: unknown/expired_data/conflicting are not confirmed", () => {
  assert.equal(FC.isConfirmedStatus("unknown"), false);
  assert.equal(FC.isConfirmedStatus("expired_data"), false);
  assert.equal(FC.isConfirmedStatus("conflicting"), false);
});

test("sortMultiLocal: orders by res_ratio descending, flags the top candidate", () => {
  const cands = [
    { i: 96, r: 0.05 },
    { i: 103, r: 0.95 },
  ];
  const sorted = FC.sortMultiLocal(cands);
  assert.equal(sorted[0].i, 103);
  assert.equal(sorted[0].isTop, true);
  assert.equal(sorted[1].i, 96);
  assert.equal(sorted[1].isTop, false);
});

test("sortMultiLocal: matches the known 02138 case (LU 103 Boston above LU 96 Worcester)", () => {
  // mirrors build_frontend_data.py's real output for ZIP 02138
  const cands = [
    { i: 15, r: 1.0, c: 95.0 },  // LU 103 Boston
    { i: 102, r: 1.0, c: 5.0 }, // LU 96 Worcester
  ];
  const sorted = FC.sortMultiLocal(cands);
  assert.equal(sorted[0].i, 15);
  assert.equal(sorted[0].isTop, true);
});

test("sortMultiLocal: ties keep input order (stable) and only the first is top", () => {
  const cands = [{ i: 1, r: 0.5 }, { i: 2, r: 0.5 }, { i: 3, r: 0.5 }];
  const sorted = FC.sortMultiLocal(cands);
  assert.deepEqual(sorted.map(c => c.i), [1, 2, 3]);
  assert.deepEqual(sorted.map(c => c.isTop), [true, false, false]);
});

test("sortMultiLocal: does not mutate the input array", () => {
  const cands = [{ i: 1, r: 0.1 }, { i: 2, r: 0.9 }];
  const copy = JSON.parse(JSON.stringify(cands));
  FC.sortMultiLocal(cands);
  assert.deepEqual(cands, copy);
});
