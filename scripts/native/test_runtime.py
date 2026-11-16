"""Guard cleanup inputs before any privileged SQL or API side effect."""
from pathlib import Path
import unittest
from unittest.mock import Mock

from runtime import Runtime, LAB, linux_path


class RuntimeTests(unittest.TestCase):
    def test_invalid_owner_cannot_reach_privileged_cleanup(self):
        runtime = Runtime(Path('artifacts/native/test'))
        runtime.sql = Mock()
        with self.assertRaises(ValueError):
            runtime.cleanup_uploads([dict(userId='1 OR 1=1', uploadDirectory='2')])
        runtime.sql.assert_not_called()

    def test_unexpected_mount_drive_is_rejected(self):
        with self.assertRaises(ValueError):
            linux_path('E:/unexpected-native-path')

    @unittest.skipUnless((LAB/'wsl').is_dir(), 'Dedicated native WSL environment is not prepared')
    def test_linux_shell_variables_are_expanded_only_in_the_target_shell(self):
        runtime=Runtime(Path('artifacts/native/test'))
        result=runtime.shell('native_roundtrip=inside; printf "%s" "$native_roundtrip"')
        self.assertEqual(result.stdout.decode(),'inside')


if __name__ == '__main__':
    unittest.main()
