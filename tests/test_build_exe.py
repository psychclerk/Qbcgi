import unittest
from unittest import mock

import build_exe


class BuildExeTests(unittest.TestCase):
    def test_build_constructs_pyinstaller_command(self):
        with mock.patch('shutil.which', return_value='/usr/bin/pyinstaller'), \
             mock.patch('subprocess.check_call') as check_call:
            rc = build_exe.build('qbcgi_test', onefile=True)
        self.assertEqual(rc, 0)
        cmd = check_call.call_args.args[0]
        self.assertIn('--onefile', cmd)
        self.assertIn('qbcgi.py', cmd)

    def test_build_returns_2_when_pyinstaller_missing(self):
        with mock.patch('shutil.which', return_value=None):
            rc = build_exe.build('qbcgi_test', onefile=True)
        self.assertEqual(rc, 2)


if __name__ == '__main__':
    unittest.main()
