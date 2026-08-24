import csv
import unittest

from wage_rules import classify_wage_candidate, extract_effective_date


def candidates():
    with open("out/wage_candidates.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def row(lu, value=None, match_type=None):
    for r in candidates():
        if r["lu_number"] == str(lu) and (value is None or r["parsed_value"] == str(value)) and (match_type is None or r["match_type"] == match_type):
            return r
    raise AssertionError(f"fixture not found: LU {lu}, {value}, {match_type}")


class WageRuleTests(unittest.TestCase):
    def test_lu1_hotel_and_navigation_are_rejected(self):
        hotel = row(1, 184, "explicit_rate")
        self.assertEqual(classify_wage_candidate(hotel, hotel["matched_text"])["reject_reason"], "negative_context")
        nav = row(1, match_type="progression_table")
        self.assertNotEqual(classify_wage_candidate(nav, nav["matched_text"])["admissible"], True)

    def test_percentage_fixtures(self):
        twelve = row(12, 50, "pct_of_journeyman")
        self.assertEqual(classify_wage_candidate(twelve, twelve["matched_text"])["value"], 50)
        self.assertEqual(classify_wage_candidate(twelve, twelve["matched_text"])["kind"], "apprentice_pct")
        twenty = row(20, 50, "pct_of_journeyman")
        self.assertEqual(classify_wage_candidate(twenty, twenty["matched_text"])["kind"], "apprentice_pct")
        self.assertEqual(classify_wage_candidate(twenty, twenty["matched_text"])["value"], 50)
        self.assertEqual(classify_wage_candidate(row(20, 80, "pct_of_journeyman"), row(20, 80, "pct_of_journeyman")["matched_text"])["value"], 80)

    def test_real_hourly_and_package_fixtures(self):
        r95 = row(95, "13.03", "explicit_rate")
        self.assertEqual(classify_wage_candidate(r95, r95["matched_text"])["kind"], "apprentice_hourly")
        self.assertTrue(classify_wage_candidate(r95, r95["matched_text"])["admissible"])
        self.assertEqual(classify_wage_candidate(row(60, "37.45", "explicit_rate_total_package"), row(60, "37.45", "explicit_rate_total_package")["matched_text"])["kind"], "journeyman_base")
        self.assertEqual(classify_wage_candidate(row(60, "49.64", "explicit_rate_total_package"), row(60, "49.64", "explicit_rate_total_package")["matched_text"])["kind"], "journeyman_total_package")
        inc = row(60, "0.75")
        self.assertEqual(classify_wage_candidate(inc, inc["matched_text"])["kind"], "raise_increment")
        table = row(82, "18.12", "explicit_rate_total_package")
        self.assertEqual(classify_wage_candidate(table, table["matched_text"])["kind"], "apprentice_hourly")

    def test_ranges_and_bounds(self):
        r129 = row(129, "51.04", "explicit_rate_base_wage")
        self.assertEqual(classify_wage_candidate(r129, r129["matched_text"])["kind"], "journeyman_base")
        self.assertEqual(classify_wage_candidate({"parsed_value": "956", "match_type": "explicit_rate"}, "journeyman wage rate $956 per hour")["reject_reason"], "implausible_value")
        self.assertEqual(classify_wage_candidate({"parsed_value": "0.0", "match_type": "explicit_rate"}, "journeyman wage rate $0.0 per hour")["reject_reason"], "implausible_value")

    def test_effective_dates(self):
        self.assertEqual(extract_effective_date("rate effective June 3, 2024"), ("2024-06-03", "day"))
        self.assertEqual(extract_effective_date("as of 6/1/2025"), ("2025-06-01", "day"))
        self.assertEqual(extract_effective_date("2025-2026 wage rates"), ("2025-01-01", "year"))


if __name__ == "__main__":
    unittest.main()
