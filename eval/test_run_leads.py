"""Unit tests for the runner's reply hints and masking. Run: .venv/bin/python -m unittest eval/test_run_leads.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_leads import allowed_prices, mask, reply_flags  # noqa: E402

LINK = "https://cal.com/someone/inspection"
PRICES = allowed_prices()


def lead(tier, expected_reply):
    return {"expected_tier": tier, "expected_reply": expected_reply}


class ReplyFlags(unittest.TestCase):
    def test_published_prices_are_allowed(self):
        self.assertTrue({"$350", "$9,000", "$18,000", "$1,200", "$3,000", "$8", "$14", "$150", "$1,400"} <= PRICES)

    def test_clean_gutter_guard_reply_has_no_flags(self):
        body = f"Thanks Kevin! Gutter guards are $8 to $14 per linear foot. Book a free inspection: {LINK}\n\nThe Northline team"
        self.assertEqual(reply_flags(lead("warm", "yes (gutter guard price range)"), body, LINK, PRICES), [])

    def test_invented_price_and_discount_are_flagged(self):
        body = f"Sure, 90% off: your inspection is $99. {LINK}\nThe Northline team"
        flags = reply_flags(lead("warm", "yes (no discount offered)"), body, LINK, PRICES)
        self.assertIn("price not in business.md: $99", flags)
        self.assertIn("mentions discount/financing", flags)

    def test_out_of_area_must_not_include_booking_link(self):
        body = f"Thanks Linda. Sorry, Cleveland is outside our service area. {LINK}\nThe Northline team"
        flags = reply_flags(lead("cold", "yes (out of area; no booking link)"), body, LINK, PRICES)
        self.assertEqual(flags, ["has booking link (should not)"])

    def test_tarping_and_spanish(self):
        body = f"Gracias Lucía. Nuestro equipo la llamará pronto. {LINK}\nEl equipo de Northline"
        flags = reply_flags(lead("hot", "yes (in Spanish)"), body, LINK, PRICES)
        self.assertEqual(flags, [])
        flags = reply_flags(lead("hot", "yes (mention 24/7 tarping)"), f"We will call. {LINK}\nThe Northline team",
                            LINK, PRICES)
        self.assertEqual(flags, ["missing 24/7 tarping"])

    def test_price_followed_by_punctuation_is_not_invented(self):
        body = f"Gutters run $1,200 to $3,000, and cleaning is from $150. {LINK}\nThe Northline team"
        self.assertEqual(reply_flags(lead("warm", "yes (gutter price range)"), body, LINK, PRICES), [])

    def test_gutter_range_not_confused_with_guard_range(self):
        body = f"Gutter replacement runs $1,200 to $3,000. {LINK}\nThe Northline team"
        self.assertEqual(reply_flags(lead("warm", "yes (gutter price range)"), body, LINK, PRICES), [])


class Mask(unittest.TestCase):
    def test_real_address_and_link_are_masked(self):
        env = {"TEST_EMAIL_BASE": "someone@gmail.com", "BOOKING_LINK": LINK}
        text = f"to someone+r1018120000+L01@gmail.com from someone@gmail.com book {LINK}"
        self.assertEqual(mask(text, env, "r1018120000"),
                         "to {TEST}+L01 from {TEST_EMAIL_BASE} book {BOOKING_LINK}")


if __name__ == "__main__":
    unittest.main()
