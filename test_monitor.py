"""Unit tests for monitor.py's visible-text normalizer (round 2, task 2/5).

The test that matters most, per Andrew's direction: prove the normalizer
isn't simply erasing everything. A normalizer that hides real content
changes alongside the noise would score a perfect false-positive rate and
be useless -- see test_real_sentence_change_still_differs and
test_program_year_change_still_differs.
"""
import unittest

import monitor


def _page(body):
    return f"""<!doctype html>
<html><head><title>IBEW Local</title>
<style>.x{{color:red}}</style>
<script>var x = 1;</script>
</head><body>{body}</body></html>"""


class TestVisibleTextNormalizerIgnoresNoise(unittest.TestCase):
    """Each case reproduces one round-1 noise category from
    out/monitor_noise_audit.csv, with only that one attribute/value
    differing between the two documents. All must hash identically."""

    def _assert_same_hash(self, body_a, body_b):
        hash_a = monitor.normalize_and_hash_visible(_page(body_a))
        hash_b = monitor.normalize_and_hash_visible(_page(body_b))
        self.assertEqual(hash_a, hash_b)

    def test_viewstate_token_ignored(self):
        self._assert_same_hash(
            '<form><input type="hidden" name="__viewstate" value="wwj3rl17gpwc3w8hnxxvqeiau2j7kk7"></form>'
            '<p>Apply for apprenticeship</p>',
            '<form><input type="hidden" name="__viewstate" value="mzqxw6a7eysbi3hfzsem3ackfmxvsagz"></form>'
            '<p>Apply for apprenticeship</p>',
        )

    def test_cache_busting_query_string_ignored(self):
        self._assert_same_hash(
            '<link rel="stylesheet" href="style.css?ver=50a2507844e876aefb9644c327e61160">'
            '<p>Apply for apprenticeship</p>',
            '<link rel="stylesheet" href="style.css?ver=7006eec51d73d2757ed56fd66c6dd0ce">'
            '<p>Apply for apprenticeship</p>',
        )

    def test_cloudflare_email_obfuscation_ignored(self):
        self._assert_same_hash(
            '<a href="/cdn-cgi/l/email-protection#97f3fefbfbf8f9d7faf2e3f4a6a3a1b9f4f8fa">email</a>'
            '<p>Apply for apprenticeship</p>',
            '<a href="/cdn-cgi/l/email-protection#05616c69696a6b45686071663431332b666a68">email</a>'
            '<p>Apply for apprenticeship</p>',
        )

    def test_s3_presigned_url_ignored(self):
        self._assert_same_hash(
            '<img src="https://s3.amazonaws.com/x?X-Amz-Date=20260813T050034Z&X-Amz-Signature=abc123">'
            '<p>Apply for apprenticeship</p>',
            '<img src="https://s3.amazonaws.com/x?X-Amz-Date=20260813T051930Z&X-Amz-Signature=def456">'
            '<p>Apply for apprenticeship</p>',
        )

    def test_hit_counter_ignored(self):
        self._assert_same_hash(
            '<div>1381744 hits since feb 16, 2006</div><p>Apply for apprenticeship</p>',
            '<div>1381749 hits since feb 16, 2006</div><p>Apply for apprenticeship</p>',
        )

    def test_tradeschoolinc_captcha_ignored(self):
        self._assert_same_hash(
            '<td>security</td><td>10 + 16 =<input type="text" id="captcha"></td>'
            '<p>Apply for apprenticeship</p>',
            '<td>security</td><td>6 + 1 =<input type="text" id="captcha"></td>'
            '<p>Apply for apprenticeship</p>',
        )

    def test_batcache_generated_stamp_ignored(self):
        self._assert_same_hash(
            '<!-- generated 2366 seconds ago --><p>Apply for apprenticeship</p>',
            '<!-- generated 5778 seconds ago --><p>Apply for apprenticeship</p>',
        )

    def test_script_and_style_content_ignored(self):
        hash_a = monitor.normalize_and_hash_visible(
            "<html><head><style>.x{color:red}</style>"
            "<script>var buildId = 'abc123';</script></head>"
            "<body><p>Apply for apprenticeship</p></body></html>")
        hash_b = monitor.normalize_and_hash_visible(
            "<html><head><style>.x{color:blue}</style>"
            "<script>var buildId = 'def456';</script></head>"
            "<body><p>Apply for apprenticeship</p></body></html>")
        self.assertEqual(hash_a, hash_b)


class TestVisibleTextNormalizerCatchesRealChanges(unittest.TestCase):
    """The test that matters most: an over-aggressive normalizer that hides
    everything would pass every test above with a trivial (empty-string)
    output. These prove real content differences still produce different
    hashes."""

    def test_real_sentence_change_still_differs(self):
        hash_a = monitor.normalize_and_hash_visible(_page("<p>Applications are now open.</p>"))
        hash_b = monitor.normalize_and_hash_visible(_page("<p>Applications are closed.</p>"))
        self.assertNotEqual(hash_a, hash_b)

    def test_program_year_change_still_differs(self):
        # Round 2 direction, explicit: a normalizer that eats program years
        # would hide exactly the changes we care about. "2026 Program" is
        # not adjacent to a date word, so the bare year must survive.
        hash_a = monitor.normalize_and_hash_visible(_page("<p>2026 Program applications open now.</p>"))
        hash_b = monitor.normalize_and_hash_visible(_page("<p>2027 Program applications open now.</p>"))
        self.assertNotEqual(hash_a, hash_b)

    def test_class_of_year_still_differs(self):
        hash_a = monitor.normalize_and_hash_visible(_page("<p>Now accepting the Class of 2030.</p>"))
        hash_b = monitor.normalize_and_hash_visible(_page("<p>Now accepting the Class of 2031.</p>"))
        self.assertNotEqual(hash_a, hash_b)


class TestContextualYearRedaction(unittest.TestCase):
    def test_copyright_year_redacted(self):
        hash_a = monitor.normalize_and_hash_visible(_page("<p>Copyright 2026 IBEW Local 1.</p>"))
        hash_b = monitor.normalize_and_hash_visible(_page("<p>Copyright 2027 IBEW Local 1.</p>"))
        self.assertEqual(hash_a, hash_b)

    def test_bare_year_not_adjacent_to_date_word_survives(self):
        text = monitor.normalize_visible_text(_page("<p>2026 Program applications.</p>"))
        self.assertIn("2026", text)


class TestExtractVisibleText(unittest.TestCase):
    def test_attributes_are_never_visible(self):
        text = monitor.extract_visible_text(
            '<a href="https://example.com/secret-token-abc123" data-x="hidden-value">Apply here</a>')
        self.assertIn("apply here".split()[0], text.lower())
        self.assertNotIn("secret-token-abc123", text)
        self.assertNotIn("hidden-value", text)

    def test_head_script_style_noscript_excluded(self):
        text = monitor.extract_visible_text(
            "<html><head><title>Title text</title></head>"
            "<body><script>scriptText</script><style>styleText{}</style>"
            "<noscript>noscriptText</noscript><p>Body text</p></body></html>")
        self.assertIn("body text", text.lower())
        self.assertNotIn("Title text", text)
        self.assertNotIn("scriptText", text)
        self.assertNotIn("styleText", text)
        self.assertNotIn("noscriptText", text)

    def test_comments_excluded(self):
        text = monitor.extract_visible_text("<p>Visible</p><!-- hidden comment -->")
        self.assertIn("visible", text.lower())
        self.assertNotIn("hidden comment", text)


if __name__ == "__main__":
    unittest.main()
