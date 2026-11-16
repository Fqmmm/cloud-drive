import unittest
from pathlib import Path
from unittest.mock import patch

from archive_experiment_logs import Redactor, native_linux_sources


class RedactionTests(unittest.TestCase):
    def test_short_code_does_not_destroy_timestamps_ids_or_hashes(self):
        policy = Redactor(['123456'])
        source = 'time=2026-11-16T12:00:00.123456+00:00 id=9912345677 hash=ab123456cd uuid=ab-123456-cd extractCode=123456'
        self.assertEqual(policy.text(source), source.replace('extractCode=123456', 'extractCode=[REDACTED]'))

    def test_structured_credentials_hidden_while_measurements_remain(self):
        source = dict(password='not-in-known-list', extractCode='000001', _token='private',
                      requests=51200, code='DEPENDENCY_UNAVAILABLE', userId='1234567890123456')
        result = Redactor().structured(source)
        self.assertEqual([result[key] for key in ['password', 'extractCode', '_token']], ['[REDACTED]'] * 3)
        self.assertEqual((result['requests'], result['code'], result['userId']), (51200, source['code'], source['userId']))
        self.assertEqual(source['password'], 'not-in-known-list')

    def test_unknown_jwt_and_share_capability_masked_idempotently(self):
        policy = Redactor()
        source = 'Bearer eyJabc123.payload456.signature789 /api/v1/s/abcdefghijklmnopqrstuv/download X-Internal-Token=private-value'
        result = policy.text(source)
        self.assertNotIn('eyJabc123', result)
        self.assertNotIn('abcdefghijklmnopqrstuv', result)
        self.assertNotIn('private-value', result)
        self.assertEqual(policy.text(result), result)

    def test_active_native_experiment_is_not_terminated(self):
        with patch('archive_experiment_logs.subprocess.check_output', return_value=b'123\n'), \
                patch('archive_experiment_logs.subprocess.run') as terminate:
            with self.assertRaises(RuntimeError): native_linux_sources(Path('unused'))
            terminate.assert_not_called()


if __name__ == '__main__': unittest.main()
