import os
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from qbcgi import QBError, render_cgi_error_response, run_script


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
        self.assertIn('X-Content-Type-Options: nosniff', out)
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

    def test_loop_limit_protection(self):
        src = '\n'.join([
            'FOR i = 1 TO 1000',
            '  PRINT STR(i)',
            'NEXT',
        ])
        with self.assertRaisesRegex(QBError, 'Loop iteration limit exceeded'):
            with mock.patch.dict(os.environ, {'QBCGI_MAX_LOOP_ITERATIONS': '10'}, clear=False):
                run_script(src)

    def test_user_defined_function_and_sub(self):
        src = '\n'.join([
            'FUNCTION ADDONE(x)',
            '  RETURN x + 1',
            'ENDFUNCTION',
            'SUB BANNER(txt)',
            '  PRINT \"[\" + txt + \"]\"',
            'ENDSUB',
            'LET v = ADDONE(4)',
            'CALL BANNER(\"result=\" + STR(v))',
        ])
        self.assertEqual(run_script(src).strip(), '[result=5]')

    def test_qbbc_compiles_and_runs_launcher(self):
        with tempfile.TemporaryDirectory() as td:
            src_path = os.path.join(td, 'hello.qbb')
            out_path = os.path.join(td, 'hello_compiled.py')
            with open(src_path, 'w', encoding='utf-8') as f:
                f.write('PRINT \"hello\"\n')

            subprocess.check_call(['python3', 'qbbc.py', src_path, out_path], cwd=os.getcwd())
            result = subprocess.check_output(['python3', out_path], text=True, cwd=os.getcwd()).strip()
            self.assertEqual(result, 'hello')

    def test_guestbook_invalid_delete_id_does_not_crash(self):
        src = Path('examples/guestbook.qbb').read_text(encoding='utf-8')
        body = b'action=delete&delete_id=abc'
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
        self.assertIn('Content-Type: text/html; charset=utf-8', out)

    def test_error_response_safe_mode(self):
        with mock.patch.dict(os.environ, {'QBCGI_ERROR_MODE': 'safe'}, clear=False):
            out = render_cgi_error_response(QBError('demo'))
        self.assertIn('Status: 500 Internal Server Error', out)
        self.assertIn('Application Error', out)
        self.assertNotIn('QBError: demo', out)

    def test_error_response_debug_mode_contains_trace(self):
        with mock.patch.dict(os.environ, {'QBCGI_ERROR_MODE': 'debug'}, clear=False):
            out = render_cgi_error_response(QBError('demo'))
        self.assertIn('QBCGI Runtime Error', out)
        self.assertIn('QBError', out)


if __name__ == '__main__':
    unittest.main()
