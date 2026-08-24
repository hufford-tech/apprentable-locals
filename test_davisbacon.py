import unittest
import csv
from decimal import Decimal

from build_local_wage_davisbacon import classification_county_qualifiers, scoped_rate_rows
from parse_davisbacon import _clean_label, classify_electrical_work, is_mangled_classification_text, local_from_code, parse_fringe


class FringeTests(unittest.TestCase):
    def test_fixed(self):
        fixed, pct, computed, flag = parse_fringe("14.91", Decimal("33.05"))
        self.assertEqual((fixed, pct, computed, flag), (Decimal("14.91"), Decimal("0"), Decimal("14.91"), ""))

    def test_percent_plus_fixed(self):
        fixed, pct, computed, flag = parse_fringe("27.43%+12.16", Decimal("40.18"))
        self.assertEqual((fixed, pct, flag), (Decimal("12.16"), Decimal("27.43"), ""))
        self.assertEqual(computed, Decimal("23.181374"))

    def test_small_percent_plus_fixed(self):
        fixed, pct, computed, flag = parse_fringe("3%+24.18", Decimal("58.00"))
        self.assertEqual((fixed, pct, computed, flag), (Decimal("24.18"), Decimal("3"), Decimal("25.92"), ""))

    def test_malformed_is_preserved_but_not_guessed(self):
        self.assertEqual(parse_fringe("20.17+a", Decimal("40")), (None, None, None, "unparsed_fringe"))

    def test_local_number(self):
        self.assertEqual(local_from_code("ELEC0038-005"), "38")
        self.assertEqual(local_from_code("ELEC12345-001"), "12345")
        self.assertEqual(local_from_code("SUOH2012-076"), "")

    def test_every_exclusion_category(self):
        cases = {
            "LINE CONSTRUCTION: LINEMAN": "line_construction",
            "ELECTRICIAN (RESIDENTIAL, 1-3 STORIES)": "primary_residential",
            "ELECTRICAL LOW VOLTAGE WIRING INSTALLER": "low_voltage_or_communications",
            "TRAFFIC SIGNAL, STREET LIGHT AND UNDERGROUND WORK": "street_or_utility_work",
            "ELECTRICIAN (TUNNEL WORK)": "tunnel_work",
            "ELECTRICIAN (JOBBING, AND MAINTENANCE AND REPAIR WORK)": "jobbing_maintenance_or_service",
            "LINE CONSTRUCTION: CABLE SPLICER": "line_construction_cable_splicer",
            "ELECTRICIANS (ELECTRICAL CONTRACTS): CABLE SPLICER": "cable_splicer_non_journeyman",
            "ELECTRICIANS: (TELEPHONE UNIT)": "telephone_unit",
            "ELECTRICIANS: (MAINTENANCE UNIT)": "maintenance_unit",
            "ELECTRICIAN Residential Construction (up to and including 4 stories)": "primary_residential",
        }
        for text, reason in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_electrical_work(text), ("excluded", reason))

    def test_residential_trap_keeps_all_other_work(self):
        self.assertEqual(
            classify_electrical_work("ELECTRICIAN: (ALL OTHER WORK, INCLUDING 4 STORIES RESIDENTIAL)"),
            ("inside_wireman", ""),
        )
        self.assertEqual(
            classify_electrical_work("ELECTRICIAN (EXCLUDES LOW VOLTAGE WIRING)"),
            ("inside_wireman", ""),
        )
        self.assertEqual(
            classify_electrical_work("CONDUCTORS DETERMINED BY THEIR FUNCTION"),
            ("excluded", "not_journeyman_electrician"),
        )

    def test_html_entities_are_not_double_escaped(self):
        self.assertEqual(classify_electrical_work("LINEMAN &amp;amp; TE"), ("excluded", "line_construction"))
        self.assertEqual(_clean_label("LINEMAN &amp;amp; TE"), "LINEMAN & TE")

    def test_county_qualifiers_scope_dublin_and_peoria(self):
        dublin = [{"state": "CA", "name": "Alameda County", "fips": "06001"}, {"state": "CA", "name": "Calaveras County", "fips": "06009"}]
        alameda = {"state": "CA", "name": "Alameda County", "fips": "06001"}
        rows = [
            {"state": "California", "counties": "California Counties of Alameda and Calaveras", "classification_text": "ELECTRICIAN (ALAMEDA COUNTY)"},
            {"state": "California", "counties": "California Counties of Alameda and Calaveras", "classification_text": "ELECTRICIAN (CALAVERAS COUNTY)"},
        ]
        self.assertEqual(classification_county_qualifiers(rows[0], dublin), {"alameda"})
        self.assertEqual([r["classification_text"] for r in scoped_rate_rows(rows, dublin, alameda)], ["ELECTRICIAN (ALAMEDA COUNTY)"])
        peoria = [{"state": "IL", "name": "Peoria County", "fips": "17143"}, {"state": "IL", "name": "Adams County", "fips": "17001"}]
        self.assertEqual(classification_county_qualifiers({"state": "Illinois", "classification_text": "ELECTRICIAN (QUINCY DIVISION - ADAMS COUNTY)"}, peoria), {"adams"})

    def test_mangled_classification_detection(self):
        self.assertTrue(is_mangled_classification_text("OR EXCLUSION OF TERMINATIONS AND TESTINGS OF CONDUCTORS"))
        self.assertFalse(is_mangled_classification_text("SOUND & COMMUNICATIONS: INSTALLER (SCOPE OF WORK)"))

    def test_round_three_rate_regressions(self):
        expected = {
            "302": ("66.26", "66.26"), "134": ("57.75", "57.75"), "3": ("62.00", "62.00"),
            "569": ("58.95", "58.95"), "98": ("70.97", "70.97"), "613": ("38.65", "38.65"),
            "38": ("46.63", "46.63"), "234": ("70.41", "77.45"),
        }
        with open("out/local_wage_davisbacon.csv", newline="", encoding="utf-8") as f:
            rows = {r["lu_number"]: r for r in csv.DictReader(f)}
        for lu, (low, high) in expected.items():
            with self.subTest(lu=lu):
                self.assertEqual((rows[lu]["journeyman_base_low"], rows[lu]["journeyman_base_high"]), (low, high))


if __name__ == "__main__":
    unittest.main()
