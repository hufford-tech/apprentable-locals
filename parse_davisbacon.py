"""Parse cached SAM.gov Davis-Bacon determinations.

This module is deliberately network-free.  ``pull_davisbacon.py`` owns all
network access and stores the JSON responses under ``raw/davisbacon`` before
this parser is ever invoked.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path


OUT = Path("out/davisbacon_rates.csv")
CACHE = Path("raw/davisbacon")
FIELDS = [
    "wd_number", "wd_modification", "wd_effective_date", "state", "counties",
    "construction_type", "classification_code", "classification_text",
    "cba_or_survey_date", "base_rate", "fringe_raw", "fringe_fixed",
    "fringe_pct", "fringe_computed", "total_rate", "is_union_rate",
    "local_number_from_code", "work_classification", "exclusion_reason", "flags",
]

# A rate identifier is a four-letter craft/union code or a survey/average/state
# identifier followed by the SAM internal suffix.  Keep the date separate: it
# is a CBA/survey date, not the determination effective date.
IDENTIFIER = re.compile(
    r"(?m)^\s*(?P<code>(?:[A-Z]{4}\d{3,6}|(?:SU|SA)[A-Z]{2}\d{4}|UAVG-[A-Z]{2})-\d{3,4})\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*$"
)
RATE = re.compile(
    r"(?ms)^\s*(?P<label>[A-Z][\s\S]{0,12000}?)\.{2,}\$?\s*"
    r"(?P<base>\d+(?:\.\d{1,2})?)\s+(?P<fringe>[^\s\r\n]+)\s*$"
)
GENERAL_DATE = re.compile(r"General Decision Number:\s*\S+\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)
STATE = re.compile(r"(?m)^\s*State:\s*([^\r\n]+)", re.I)
CONSTRUCTION = re.compile(r"(?m)^\s*Construction Types?:\s*([^\r\n]+)", re.I)
COUNTIES = re.compile(r"(?ms)^\s*Count(?:y|ies):\s*(.+?)(?=\n\s*\n|\n\s*(?:[A-Z ]+CONSTRUCTION|Modification Number)|\Z)", re.I)

# Class-I display only: exclusions are deliberately explicit and independently
# named so the test suite documents every boundary.  Do not collapse these into
# a broad "electric" or "residential" test: a determinations can say
# "including 4 stories residential" while still naming the commercial inside
# wireman classification.
LINE_CONSTRUCTION_RE = re.compile(r"\b(?:LINE CONSTRUCTION|LINEMAN|GROUNDMAN|FLAGMAN|SUBSTATION|SWITCHING|OVERHEAD\s+AND\s+UNDERGROUND|\bPOLE\b)", re.I)
LOW_VOLTAGE_RE = re.compile(r"\b(?:LOW[ -]?VOLTAGE|TELEDATA|SOUND|COMMUNICATION|CATV|TELEVISION|RADIO|FIBER[ -]?OPTIC|MASTER TELEVISION DISTRIBUTION)\b", re.I)
EXCLUDED_SCOPE_RE = re.compile(r"\bEXCLUD(?:ES|ING)\s+(?:LOW[ -]?VOLTAGE|SOUND|COMMUNICATION|CATV|TELEVISION|RADIO|FIBER[ -]?OPTIC|MASTER TELEVISION DISTRIBUTION)\b", re.I)
STREET_WORK_RE = re.compile(r"\b(?:TRAFFIC SIGNAL|STREET LIGHT|UTILITY)\b", re.I)
TUNNEL_RE = re.compile(r"\bTUNNEL\b", re.I)
SERVICE_TIER_RE = re.compile(r"\b(?:JOBBING|MAINTENANCE\s+AND\s+REPAIR|SERVICE\s+OF)\b", re.I)
MAINTENANCE_UNIT_RE = re.compile(r"\bMAINTENANCE\s+UNIT\b", re.I)
TELEPHONE_UNIT_RE = re.compile(r"\bTELEPHONE\s+UNIT\b", re.I)
CABLE_SPLICER_RE = re.compile(r"\bCABLE\s+SPLICER\b", re.I)
# "ELECTRICIAN (RESIDENTIAL...)" is primary residential.  The intentional
# negative lookahead preserves "ALL OTHER WORK, INCLUDING ... RESIDENTIAL".
PRIMARY_RESIDENTIAL_RE = re.compile(r"\bELECTRICIANS?\s*(?:\([^)]*\bRESIDENTIAL\b|:\s*RESIDENTIAL\b)", re.I)
DIRECT_RESIDENTIAL_RE = re.compile(r"\bELECTRICIANS?\s+RESIDENTIAL(?:\s+CONSTRUCTION)?\b", re.I)
QUALIFIER_RE = re.compile(r"\b(?:CONTRACTS?\s+OF|UNDER\s+\$|OVER\s+\$|LESS\s+THAN\s+\$|MORE\s+THAN\s+\$)\b", re.I)
ELECTRICIAN_RE = re.compile(r"\bELECTRICIANS?\b", re.I)
MANGLED_CLASSIFICATION_RE = re.compile(r"^(?:OR\s+EXCLUSION\b|CONDUCTORS\s+DETERMINED\b|OF\s+TERMINATIONS\b)", re.I)


def money(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else ""


def parse_fringe(raw: str, base: Decimal) -> tuple[Decimal | None, Decimal | None, Decimal | None, str]:
    """Return fixed, percentage, computed fringe and a parse flag.

    SAM formats are intentionally retained verbatim in the CSV.  We only
    calculate for the published fixed / pct+fixed forms; an unfamiliar form is
    visible and excluded from arithmetic instead of guessed at.
    """
    token = (raw or "").strip().replace(" ", "")
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            fixed = Decimal(token)
            return fixed, Decimal("0"), fixed, ""
        m = re.fullmatch(r"(\d+(?:\.\d+)?)%\+(\d+(?:\.\d+)?)", token)
        if m:
            pct, fixed = Decimal(m.group(1)), Decimal(m.group(2))
            return fixed, pct, base * pct / Decimal("100") + fixed, ""
        m = re.fullmatch(r"(\d+(?:\.\d+)?)%", token)
        if m:
            pct = Decimal(m.group(1))
            return Decimal("0"), pct, base * pct / Decimal("100"), ""
    except InvalidOperation:
        pass
    return None, None, None, "unparsed_fringe"


def local_from_code(code: str) -> str:
    m = re.match(r"^ELEC(\d+)-\d+$", code or "", re.I)
    return str(int(m.group(1))) if m else ""


def is_ibew_union_code(code: str) -> bool:
    # ELEC identifiers name the electrical local directly.  SU values are
    # survey rates; UAVG/SA/SC do not name an IBEW local and are never blended.
    return bool(re.match(r"^ELEC\d+-\d+$", code or "", re.I))


def classify_electrical_work(classification_text: str) -> tuple[str, str]:
    """Classify an electrical rate for Class-I inside-wireman display.

    A cable splicer is excluded even in an otherwise inside classification: it
    is a different, higher-rated classification, not the journeyman wireman
    baseline.  The reason distinguishes line-construction cable work from
    inside electrical-contract cable work for auditing.
    """
    text = _decode_html(str(classification_text or ""))
    if LINE_CONSTRUCTION_RE.search(text):
        return "excluded", "line_construction_cable_splicer" if CABLE_SPLICER_RE.search(text) else "line_construction"
    if CABLE_SPLICER_RE.search(text):
        return "excluded", "cable_splicer_non_journeyman"
    if PRIMARY_RESIDENTIAL_RE.search(text) or DIRECT_RESIDENTIAL_RE.search(text):
        return "excluded", "primary_residential"
    if LOW_VOLTAGE_RE.search(text) and not EXCLUDED_SCOPE_RE.search(text):
        return "excluded", "low_voltage_or_communications"
    if STREET_WORK_RE.search(text):
        return "excluded", "street_or_utility_work"
    if TUNNEL_RE.search(text):
        return "excluded", "tunnel_work"
    if SERVICE_TIER_RE.search(text):
        return "excluded", "jobbing_maintenance_or_service"
    if MAINTENANCE_UNIT_RE.search(text):
        return "excluded", "maintenance_unit"
    if TELEPHONE_UNIT_RE.search(text):
        return "excluded", "telephone_unit"
    if not ELECTRICIAN_RE.search(text):
        return "excluded", "not_journeyman_electrician"
    return "inside_wireman", ""


def _clean_label(value: str) -> str:
    value = _decode_html(value or "")
    value = re.sub(r"\s+", " ", value).strip(" .")
    # The per-identifier rate table repeats this header; it is not part of
    # the craft name and would otherwise pollute every first row.
    return re.sub(r"^Rates\s+Fringes\s+", "", value, flags=re.I)


def is_mangled_classification_text(value: str) -> bool:
    """Detect a parser fragment that lacks the classification's leading label."""
    return bool(MANGLED_CLASSIFICATION_RE.search(_clean_label(value)))


def _decode_html(value: str) -> str:
    """Decode nested entities emitted by some SAM document serializations."""
    for _ in range(3):
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    return value


def _metadata(data: dict) -> tuple[str, str, str, str, str]:
    document = data.get("document", "") or ""
    number = str(data.get("fullReferenceNumber") or data.get("wd_number") or "")
    revision = str(data.get("revisionNumber") if data.get("revisionNumber") is not None else data.get("wd_modification") or "")
    header = GENERAL_DATE.search(document)
    raw_effective = header.group(1) if header else str(data.get("publishDate") or "")
    try:
        effective = __import__("datetime").datetime.strptime(raw_effective, "%m/%d/%Y").date().isoformat()
    except ValueError:
        effective = raw_effective
    state = (STATE.search(document).group(1).strip() if STATE.search(document) else "")
    construction = (CONSTRUCTION.search(document).group(1).strip() if CONSTRUCTION.search(document) else ", ".join(data.get("constructionType") or []))
    county_match = COUNTIES.search(document)
    counties = _clean_label(county_match.group(1)) if county_match else ""
    return number, revision, effective, state, counties or ""


def rows_for_determination(data: dict) -> list[dict]:
    document = (data.get("document") or "").replace("\r\n", "\n")
    number, revision, effective, state, counties = _metadata(data)
    constructions = ", ".join(data.get("constructionType") or []) or (CONSTRUCTION.search(document).group(1).strip() if CONSTRUCTION.search(document) else "")
    matches = list(IDENTIFIER.finditer(document))
    rows: list[dict] = []
    for i, identifier in enumerate(matches):
        block = document[identifier.end():matches[i + 1].start() if i + 1 < len(matches) else len(document)]
        # End before SAM's explanatory material.  It contains rate examples
        # that are not classifications on this determination.
        block = block.split("END OF GENERAL DECISION", 1)[0].split("WELDERS - Receive", 1)[0]
        for rate in RATE.finditer(block):
            try:
                base = Decimal(rate.group("base"))
            except InvalidOperation:
                continue
            fixed, pct, computed, flag = parse_fringe(rate.group("fringe"), base)
            total = base + computed if computed is not None else None
            code = identifier.group("code")
            label = _clean_label(rate.group("label"))
            work_classification, exclusion_reason = classify_electrical_work(label)
            if is_mangled_classification_text(label):
                flag = ";".join(filter(None, [flag, "mangled_classification_text"]))
            rows.append({
                "wd_number": number, "wd_modification": revision,
                "wd_effective_date": effective, "state": state, "counties": counties,
                "construction_type": constructions, "classification_code": code,
                "classification_text": label, "cba_or_survey_date": identifier.group("date"),
                "base_rate": money(base), "fringe_raw": rate.group("fringe"),
                "fringe_fixed": money(fixed), "fringe_pct": money(pct),
                "fringe_computed": money(computed), "total_rate": money(total),
                "is_union_rate": "true" if is_ibew_union_code(code) else "false",
                "local_number_from_code": local_from_code(code),
                "work_classification": work_classification, "exclusion_reason": exclusion_reason,
                "flags": flag,
            })
    return rows


def parse_cache(cache_dir: Path = CACHE, out_path: Path = OUT) -> list[dict]:
    # A coverage pull can retain revision 0 while a targeted validation fetch
    # adds a newer revision.  Parse only the newest cached revision for each
    # WD; otherwise stale rows become a false geographic wage range.
    newest: dict[str, tuple[int, dict]] = {}
    for path in sorted(cache_dir.glob("*.json")):
        if path.name.endswith(".history.json") or path.name.endswith(".manifest.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            number = str(data.get("fullReferenceNumber") or data.get("wd_number") or "")
            revision = int(data.get("revisionNumber") if data.get("revisionNumber") is not None else data.get("wd_modification") or -1)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("document") and number and (number not in newest or revision > newest[number][0]):
            newest[number] = (revision, data)
    rows: list[dict] = []
    for _, data in newest.values():
        rows.extend(rows_for_determination(data))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=str(CACHE))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    rows = parse_cache(Path(args.cache), Path(args.out))
    print(f"parsed rows: {len(rows)}")


if __name__ == "__main__":
    main()
