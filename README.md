# QBCGI

QBCGI is a **QBasic-like scripting dialect** for building CGI web apps with SQLite.
It is designed so non-technical users can write simple scripts like:

- `LET`, `IF/ELSE/ENDIF`, `FOR/NEXT`
- `PRINT` for HTML output
- `CGI PARAM` for form/query values
- `SQL OPEN`, `SQL EXEC`, `SQL QUERY`

## Quick start

```bash
python3 qbcgi.py examples/guestbook.qbb --cgi
```

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
- `PARAM(name, default)`
- `ROWCOUNT(list)`

## Deploying as CGI

1. Make sure Python 3 is installed on the server.
2. Put this repo where your web server can execute CGI scripts.
3. Mark `run_cgi.py` executable.
4. Configure your server to run it as CGI/FastCGI.

`run_cgi.py` loads `examples/guestbook.qbb` and outputs HTTP headers + HTML.

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
