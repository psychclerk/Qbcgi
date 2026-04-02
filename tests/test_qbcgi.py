import os
import tempfile
import unittest
from io import BytesIO
from unittest import mock

from qbcgi import run_script


class _FakeStdin:
    def __init__(self, data: bytes):
        self.buffer = BytesIO(data)


class QBCGIRuntimeTests(unittest.TestCase):
    def test_basic_equality_and_string_literal(self):
        src = '\n'.join([
            'LET x = 1',
            'IF x = 1 AND "a=b" = "a=b" THEN',
            '  PRINT "ok"',
            'ELSE',
            '  PRINT "bad"',
            'ENDIF',
        ])
        self.assertEqual(run_script(src).strip(), 'ok')

    def test_sql_exec_and_query_with_commas_in_sql(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, 't.db')
            src = f'\n'.join([
                f'SQL OPEN "{db_path}"',
                'SQL EXEC "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT, note TEXT)"',
                'SQL EXEC "INSERT INTO items(name, note) VALUES (?, ?)", "Ana", "hello,world"',
                'SQL QUERY "SELECT name, note FROM items" INTO rows',
                'LET r = rows[0]',
                'PRINT r.name + ":" + r.note',
            ])
            self.assertEqual(run_script(src).strip(), 'Ana:hello,world')

    def test_cgi_mode_includes_default_header_and_param(self):
        src = '\n'.join([
            'CGI PARAM "name" INTO name DEFAULT "Guest"',
            'PRINT "Hi " + name',
        ])
        with mock.patch.dict(os.environ, {'REQUEST_METHOD': 'GET', 'QUERY_STRING': 'name=Sam'}, clear=False):
            out = run_script(src, cgi_mode=True)
        self.assertIn('Content-Type: text/html; charset=utf-8', out)
        self.assertTrue(out.rstrip().endswith('Hi Sam'))

    def test_cgi_post_urlencoded_without_cgi_module(self):
        src = '\n'.join([
            'CGI PARAM "name" INTO name DEFAULT "Guest"',
            'PRINT "Hi " + name',
        ])
        body = b'name=Lee'
        with (
            mock.patch.dict(
                os.environ,
                {
                    'REQUEST_METHOD': 'POST',
                    'CONTENT_TYPE': 'application/x-www-form-urlencoded',
                    'CONTENT_LENGTH': str(len(body)),
                    'QUERY_STRING': '',
                },
                clear=False,
            ),
            mock.patch('sys.stdin', _FakeStdin(body)),
        ):
            out = run_script(src, cgi_mode=True)
        self.assertTrue(out.rstrip().endswith('Hi Lee'))


if __name__ == '__main__':
    unittest.main()
