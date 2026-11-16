"""Checks for project isolation, redaction and update identity evidence."""
import unittest

from e2_support import changed_services, sanitize, validate_project


class EvidenceTests(unittest.TestCase):
    def test_mutating_context_rejects_the_existing_course_project(self):
        with self.assertRaises(ValueError):
            validate_project("cloud-drive-course")
        self.assertEqual(validate_project("cloud-drive-e2-20261116"), "cloud-drive-e2-20261116")

    def test_container_restart_is_detected_even_if_id_did_not_change(self):
        before = [dict(service="file-service", id="same", started="a", image_id="i"),
                  dict(service="share-service", id="old", started="a", image_id="i")]
        after = [dict(service="file-service", id="same", started="b", image_id="i"),
                 dict(service="share-service", id="new", started="c", image_id="j")]
        self.assertEqual(changed_services(before, after), {"file-service", "share-service"})

    def test_log_redaction_keeps_measurements_and_removes_capabilities(self):
        token = "eyJabcdefghijk.abcdefghijklmnop.abcdefghijklmnop"
        result = sanitize("secret-abcdef /s/" + "a" * 22 + " " + token + " durationMs=23", ["secret-abcdef"])
        self.assertNotIn("secret-abcdef", result)
        self.assertNotIn("a" * 22, result)
        self.assertNotIn(token, result)
        self.assertIn("durationMs=23", result)


if __name__ == "__main__":
    unittest.main()
