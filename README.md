# QBCGI

QBCGI is a **QBasic-like scripting dialect** for building CGI web apps with SQLite.
It is designed so non-technical users can write simple scripts like:

- `LET`, `IF/ELSE/ENDIF`, `FOR/NEXT`
- `PRINT` for HTML output (Bootstrap-friendly page generation)
- `CGI PARAM` for form/query values
- `SQL OPEN`, `SQL EXEC`, `SQL QUERY`

## Quick start

```bash
python3 qbcgi.py examples/guestbook.qbb --cgi
```

## Compile `.qbb` to executable launcher (PHP-like workflow)

You can compile a `.qbb` file into an executable Python launcher:

```bash
python3 qbbc.py examples/guestbook.qbb build/guestbook_app.py --cgi
./build/guestbook_app.py
```

This lets you deploy pre-generated executables and invoke them similarly to script handlers.

## Build `qbcgi.py` itself into an executable runtime

If you want a single executable that interprets `.qbb` files at runtime (like `php file.php`), build it with:

```bash
python3 build_exe.py --name qbcgi
./dist/qbcgi examples/guestbook.qbb --cgi
```

On Windows this will produce `dist\\qbcgi.exe`.

Run the test file:

```bash
python3 -m unittest -v tests/test_qbcgi.py
```

To test like a CGI POST request locally:

```bash
REQUEST_METHOD=POST \
CONTENT_TYPE=application/x-www-form-urlencoded \
CONTENT_LENGTH=24 \
python3 qbcgi.py examples/guestbook.qbb --cgi <<< "name=Ana&message=Hello"
```

## Language reference

### Variables and output

```basic
LET name = "Ana"
PRINT "Hello " + name
```

### Conditionals

```basic
IF LEN(name) > 0 THEN
  PRINT "ok"
ELSE
  PRINT "missing"
ENDIF
```

### Loops

```basic
FOR i = 1 TO 3
  PRINT STR(i)
NEXT
```

### User-defined procedures

```basic
FUNCTION AddTax(amount)
  RETURN amount * 1.1
ENDFUNCTION

SUB Say(msg)
  PRINT msg
ENDSUB

LET total = AddTax(100)
CALL Say("Total=" + STR(total))
```

### CGI input

```basic
CGI PARAM "name" INTO name DEFAULT "Guest"
```

### SQLite

```basic
SQL OPEN "./app.db"
SQL EXEC "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, name TEXT)"
SQL EXEC "INSERT INTO t(name) VALUES (?)", "Ana"
SQL QUERY "SELECT id, name FROM t" INTO rows
```

### Available expression functions

- `LEN(x)`, `INT(x)`, `FLOAT(x)`, `STR(x)`
- `UPPER(x)`, `LOWER(x)`, `ESCAPE(x)`
- `ISNUMERIC(x)`
- `PARAM(name, default)`
- `ROWCOUNT(list)`

## Deploying as CGI

1. Make sure Python 3 is installed on the server.
2. Put this repo where your web server can execute CGI scripts.
3. Mark `run_cgi.py` executable.
4. Configure your server to run it as CGI/FastCGI.

`run_cgi.py` loads `examples/guestbook.qbb` and outputs HTTP headers + HTML.  
The example includes a Bootstrap-based full interface (form + table + delete actions).

## Notes

- SQLite parameter binding is used (`?`) for safe inserts and queries.
- HTML escaping via `ESCAPE(...)` helps prevent XSS in rendered output.
- On script errors, CGI mode returns HTTP 500 with a readable error message.

## Production readiness

Short answer: **not yet at PHP production maturity**.

This project is currently a compact interpreter/demo and should be treated as an
early-stage runtime. Before production use, you should add:

1. **Security hardening**
   - Request size limits / rate limiting.
   - Strong sandboxing and stricter expression/runtime guards.
   - Structured allow-lists for filesystem/database access.
2. **Operational robustness**
   - Connection pooling / worker model (instead of plain CGI process-per-request).
   - Timeouts, graceful shutdown, and backpressure handling.
   - Structured logging + request IDs + metrics.
3. **Quality gates**
   - Broader automated test coverage (error paths, malformed scripts, load cases).
   - Static analysis and CI checks.
4. **Language/runtime stability**
   - Versioned language spec and compatibility guarantees.
   - Migration tooling, packaging, and release process.

### Built-in runtime safety limits

You can tune runtime limits via environment variables:

- `QBCGI_MAX_REQUEST_BYTES` (default: `1048576`)
- `QBCGI_MAX_OUTPUT_BYTES` (default: `2097152`)
- `QBCGI_MAX_LOOP_ITERATIONS` (default: `100000`)
- `QBCGI_MAX_SQL_ROWS` (default: `10000`)

### Error description mechanism (for HTTP 500)

- Default (`QBCGI_ERROR_MODE=safe`): returns an HTML error page with a short **Error ID** and no stack trace.
- Debug (`QBCGI_ERROR_MODE=debug`): returns detailed traceback in the HTML response for diagnostics.

To enable debug mode:

```bash
# one command only
QBCGI_ERROR_MODE=debug python3 qbcgi.py examples/guestbook.qbb --cgi

# or for current shell session
export QBCGI_ERROR_MODE=debug
python3 qbcgi.py examples/guestbook.qbb --cgi
```

For CGI/FastCGI servers, set the environment variable in server config:

```apache
SetEnv QBCGI_ERROR_MODE debug
```

```nginx
fastcgi_param QBCGI_ERROR_MODE debug;
```
