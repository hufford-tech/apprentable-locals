/* Pure search/status-rendering logic, extracted out of page_template.html so
 * it can be unit tested with `node --test test_finder_core.js` (frontend
 * task 10). No DOM access, no globals besides what's passed in -- safe to
 * run in Node or inline into a browser <script>.
 *
 * Exposed as window.FinderCore in a browser (page_template.html loads this
 * before its own <script>) and as module.exports in Node.
 */
(function (root) {
  "use strict";

  const LABEL = {
    open: "Accepting applications now",
    rolling: "Accepts applications on an ongoing basis",
    closed_pending: "Not open yet",
    closed: "Applications closed",
    expired_data: "Last posted window has passed",
    conflicting: "Conflicting information posted",
    unknown: "Status not published",
  };
  const NOTE = {
    open: "A posted application window is open today.",
    rolling: "This local takes applications year-round or on a repeating schedule.",
    closed_pending: "A future window is posted. Get notified when it opens.",
    closed: "The local has posted that applications are closed.",
    expired_data: "The most recent window on their site has ended and nothing newer is posted.",
    conflicting: "Their site says more than one thing. Confirm with the local before relying on this.",
    unknown: "We could not confirm a status from their website. Contact the local directly.",
  };
  const CONF_LABEL = { h: "high", m: "medium", l: "low", "": "—" };
  const CONFIRMED_STATUSES = ["open", "rolling", "closed_pending", "closed"];

  /**
   * Classify a raw search box value as a ZIP (complete or still-typing) or a
   * city-name query. Never touches the DOM.
   * @param {string} raw
   * @returns {{kind:'empty'}|{kind:'zip_incomplete'}|{kind:'zip', zip5:string}|{kind:'city', needle:string}}
   */
  function normalizeZip(raw) {
    const v = (raw || "").trim();
    if (!v) return { kind: "empty" };
    if (/^\d{3,5}$/.test(v)) {
      if (v.length < 5) return { kind: "zip_incomplete" };
      return { kind: "zip", zip5: v.padStart(5, "0") };
    }
    return { kind: "city", needle: v.toLowerCase() };
  }

  /**
   * Prefix-match "City, ST" keys against a lowercase needle.
   * @param {string[]} cityKeys
   * @param {string} needle already-lowercased
   * @param {number} limit
   */
  function matchCities(cityKeys, needle, limit) {
    limit = limit == null ? 8 : limit;
    return cityKeys.filter(k => k.toLowerCase().startsWith(needle)).slice(0, limit);
  }

  /**
   * Union the local-index arrays for a set of matched city keys.
   * @param {Object<string, number[]>} cityIndex
   * @param {string[]} matchedKeys
   * @returns {number[]} sorted ascending
   */
  function unionCityIndexes(cityIndex, matchedKeys) {
    const set = new Set();
    matchedKeys.forEach(k => (cityIndex[k] || []).forEach(i => set.add(i)));
    return [...set].sort((a, b) => a - b);
  }

  function statusLabel(status) {
    return LABEL[status] || LABEL.unknown;
  }

  function statusNote(status) {
    return NOTE[status] || NOTE.unknown;
  }

  function confidenceLabel(cf) {
    return CONF_LABEL[cf] || CONF_LABEL[""];
  }

  function isConfirmedStatus(status) {
    return CONFIRMED_STATUSES.indexOf(status) !== -1;
  }

  // Task 12: display-layer mapping only. Collapses compute_status.py's 8 raw
  // computed_status values down to the 4 candidate-facing states. Never
  // changes a computed status value -- compute_status.py itself is untouched.
  //   open_now    <- open, expected_open
  //   always      <- rolling
  //   opens_date  <- closed_pending, or closed with a known next_open_date
  //   unconfirmed <- expired_data, conflicting, unknown, and closed with no
  //                  next_open_date (the "we don't know" categories). Always
  //                  rendered neutral/gray, never red -- a closed local is a
  //                  future application window, not a failure state.
  const DISPLAY_LABEL = {
    open_now: "Open now",
    always: "Always accepting",
    unconfirmed: "Unconfirmed – check with the local",
  };
  // Non-color carrier (WCAG 1.4.1): each state also gets its own glyph.
  const DISPLAY_SHAPE = { open_now: "●", always: "◆", opens_date: "▲", unconfirmed: "■" };

  function displayStatusKey(status, nextOpen) {
    if (status === "open" || status === "expected_open") return "open_now";
    if (status === "rolling") return "always";
    if (status === "closed_pending" || (status === "closed" && nextOpen)) return "opens_date";
    return "unconfirmed";
  }

  function displayStatusLabel(status, nextOpen, fmtDateFn) {
    const key = displayStatusKey(status, nextOpen);
    if (key === "opens_date") return "Opens " + fmtDateFn(nextOpen);
    return DISPLAY_LABEL[key];
  }

  /**
   * Sort multi-local ZIP candidates by res_ratio descending (ties keep
   * input order) and flag the first as the most-likely match. Does not
   * mutate the input array.
   * @param {Array<{r:number}>} candidates
   * @returns {Array<{r:number, isTop:boolean}>}
   */
  function sortMultiLocal(candidates) {
    return candidates
      .map((c, i) => ({ c, i }))
      .sort((a, b) => (b.c.r - a.c.r) || (a.i - b.i))
      .map((entry, rank) => Object.assign({}, entry.c, { isTop: rank === 0 }));
  }

  const api = {
    LABEL, NOTE, CONF_LABEL, CONFIRMED_STATUSES,
    DISPLAY_LABEL, DISPLAY_SHAPE,
    normalizeZip, matchCities, unionCityIndexes,
    statusLabel, statusNote, confidenceLabel, isConfirmedStatus,
    displayStatusKey, displayStatusLabel,
    sortMultiLocal,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.FinderCore = api;
  }
})(typeof window !== "undefined" ? window : this);
