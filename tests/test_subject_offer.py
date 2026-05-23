import unittest

from services.subject_offer import MAILING_SUBJECT_OFFER, sanitize_email_subject


class SubjectOfferTest(unittest.TestCase):
    def test_mailing_subject_marker(self) -> None:
        self.assertEqual(MAILING_SUBJECT_OFFER, "OFFER")

    def test_sanitize(self) -> None:
        self.assertEqual(sanitize_email_subject("a\nb"), "a b")


if __name__ == "__main__":
    unittest.main()
