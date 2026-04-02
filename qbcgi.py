#!/usr/bin/env python3
"""QBCGI: A tiny QBasic-like dialect for CGI web apps with SQLite3 support."""
from __future__ import annotations

import argparse
import ast
import html
import io
import os
import sqlite3
import sys
from email.parser import BytesParser
from email.policy import default as email_policy
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs


class QBError(Exception):
    """Raised for script/runtime errors with friendly messages."""


@dataclass
class ExecContext:
    vars: dict[str, Any]
    headers: list[tuple[str, str]]
    output: list[str]
    db: sqlite3.Connection | None
    cgi_params: dict[str, list[str]]
    max_output_bytes: int
    max_loop_iterations: int
    max_sql_rows: int
    output_bytes: int = 0


class DotDict(dict):
    """Dict with attribute access for easier script usage."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def _parse_cgi_params(max_request_bytes: int) -> dict[str, list[str]]:
    def parse_multipart(body: bytes, content_type: str) -> dict[str, list[str]]:
        headers = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        message = BytesParser(policy=email_policy).parsebytes(headers + body)
        fields: dict[str, list[str]] = {}
        if not message.is_multipart():
            return fields

        for part in message.iter_parts():
            disposition = part.get("Content-Disposition", "")
            if "form-data" not in disposition:
                continue
            name = part.get_param("name", header="Content-Disposition")
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            value = payload.decode(charset, errors="replace")
            fields.setdefault(name, []).append(value)
        return fields

    method = os.environ.get("REQUEST_METHOD", "GET").upper()
    params = parse_qs(os.environ.get("QUERY_STRING", ""), keep_blank_values=True)

    if method == "POST":
        ctype = os.environ.get("CONTENT_TYPE", "")
        length = int(os.environ.get("CONTENT_LENGTH", "0") or "0")
        if length > max_request_bytes:
            raise QBError(f"Request body too large ({length} bytes)")
        body = sys.stdin.buffer.read(length)
        if ctype.startswith("application/x-www-form-urlencoded"):
            post = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
            for key, values in post.items():
                params.setdefault(key, []).extend(values)
        elif ctype.startswith("multipart/form-data"):
            post = parse_multipart(body, ctype)
            for key, values in post.items():
                params.setdefault(key, []).extend(values)

    return params


class SafeEvaluator:
    def __init__(self, ctx: ExecContext):
        self.ctx = ctx
        self.functions: dict[str, Callable[..., Any]] = {
            "LEN": lambda x: len(x),
            "INT": lambda x: int(x),
            "FLOAT": lambda x: float(x),
            "STR": lambda x: str(x),
            "UPPER": lambda x: str(x).upper(),
            "LOWER": lambda x: str(x).lower(),
            "ESCAPE": lambda x: html.escape(str(x), quote=True),
            "PARAM": self.param,
            "ROWCOUNT": self.rowcount,
        }

    def _normalize_expr(self, expr: str) -> str:
        out: list[str] = []
        word: list[str] = []
        i = 0
        in_string = False
        quote = ""

        def flush_word() -> None:
            if not word:
                return
            token = "".join(word)
            upper = token.upper()
            if upper == "AND":
                out.append("and")
            elif upper == "OR":
                out.append("or")
            elif upper == "NOT":
                out.append("not")
            else:
                out.append(token)
            word.clear()

        while i < len(expr):
            ch = expr[i]
            nxt = expr[i + 1] if i + 1 < len(expr) else ""

            if in_string:
                out.append(ch)
                if ch == quote:
                    in_string = False
                    quote = ""
                i += 1
                continue

            if ch in ('"', "'"):
                flush_word()
                in_string = True
                quote = ch
                out.append(ch)
                i += 1
                continue

            if ch.isalnum() or ch == "_":
                word.append(ch)
                i += 1
                continue

            flush_word()

            if ch == "<" and nxt == ">":
                out.append("!=")
                i += 2
                continue

            if ch == "=":
                prev = expr[i - 1] if i > 0 else ""
                if prev in ("<", ">", "!", "=") or nxt == "=":
                    out.append("=")
                else:
                    out.append("==")
                i += 1
                continue

            out.append(ch)
            i += 1

        flush_word()
        return "".join(out)

    def param(self, key: str, default: Any = "") -> Any:
        values = self.ctx.cgi_params.get(str(key), [])
        return values[0] if values else default

    def rowcount(self, value: Any) -> int:
        return len(value) if hasattr(value, "__len__") else 0

    def eval(self, expr: str) -> Any:
        expr = self._normalize_expr(expr)
        try:
            node = ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            raise QBError(f"Invalid expression: {expr}") from exc
        return self._eval_node(node.body)

    def _eval_node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self.ctx.vars.get(node.id, "")
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            raise QBError("Unsupported operator")
        if isinstance(node, ast.UnaryOp):
            value = self._eval_node(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return +value
            if isinstance(node.op, ast.Not):
                return not value
            raise QBError("Unsupported unary operator")
        if isinstance(node, ast.BoolOp):
            values = [self._eval_node(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise QBError("Unsupported boolean operator")
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = self._eval_node(comp)
                ok = (
                    (isinstance(op, ast.Eq) and left == right)
                    or (isinstance(op, ast.NotEq) and left != right)
                    or (isinstance(op, ast.Lt) and left < right)
                    or (isinstance(op, ast.LtE) and left <= right)
                    or (isinstance(op, ast.Gt) and left > right)
                    or (isinstance(op, ast.GtE) and left >= right)
                )
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise QBError("Only simple function calls are allowed")
            name = node.func.id.upper()
            fn = self.functions.get(name)
            if not fn:
                raise QBError(f"Unknown function: {name}")
            args = [self._eval_node(arg) for arg in node.args]
            return fn(*args)
        if isinstance(node, ast.Attribute):
            value = self._eval_node(node.value)
            if isinstance(value, dict):
                return value.get(node.attr, "")
            return getattr(value, node.attr)
        if isinstance(node, ast.Subscript):
            value = self._eval_node(node.value)
            key = self._eval_node(node.slice)
            return value[key]
        if isinstance(node, ast.List):
            return [self._eval_node(elt) for elt in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(elt) for elt in node.elts)
        raise QBError(f"Unsupported expression: {ast.dump(node)}")


@dataclass
class Block:
    kind: str
    header: tuple[Any, ...]
    body: list[Any]
    else_body: list[Any] | None = None


class Parser:
    def __init__(self, source: str):
        self.lines = source.splitlines()

    def parse(self) -> list[Any]:
        body, _ = self._parse_block(0, terminators=set())
        return body

    def _strip_comment(self, line: str) -> str:
        stripped = line.lstrip()
        if stripped.startswith("'"):
            return ""
        return line.strip()

    def _parse_block(self, start: int, terminators: set[str]) -> tuple[list[Any], int]:
        body: list[Any] = []
        i = start
        while i < len(self.lines):
            raw = self._strip_comment(self.lines[i])
            i += 1
            if not raw:
                continue
            upper = raw.upper()
            if upper in terminators:
                return body, i - 1

            if upper.startswith("REM "):
                continue
            if upper.startswith("IF ") and upper.endswith(" THEN"):
                cond = raw[3:-5].strip()
                if_body, end_if = self._parse_block(i, {"ELSE", "ENDIF"})
                i = end_if + 1
                else_body = None
                if self._strip_comment(self.lines[end_if]).upper() == "ELSE":
                    else_body, end2 = self._parse_block(i, {"ENDIF"})
                    i = end2 + 1
                body.append(Block("if", (cond,), if_body, else_body))
                continue

            if upper.startswith("FOR ") and " TO " in upper:
                spec = raw[4:]
                left, right = spec.split(" TO ", 1)
                var, start_expr = left.split("=", 1)
                step_expr = "1"
                if " STEP " in right.upper():
                    idx = right.upper().index(" STEP ")
                    end_expr = right[:idx]
                    step_expr = right[idx + 6 :]
                else:
                    end_expr = right
                loop_body, end_loop = self._parse_block(i, {"NEXT"})
                i = end_loop + 1
                body.append(Block("for", (var.strip(), start_expr.strip(), end_expr.strip(), step_expr.strip()), loop_body))
                continue

            if upper.startswith("FOREACH ") and " IN " in upper:
                spec = raw[8:]
                var, iterable = spec.split(" IN ", 1)
                loop_body, end_loop = self._parse_block(i, {"NEXT"})
                i = end_loop + 1
                body.append(Block("foreach", (var.strip(), iterable.strip()), loop_body))
                continue

            body.append(raw)

        if terminators:
            raise QBError(f"Missing block terminator: one of {', '.join(sorted(terminators))}")
        return body, i


class Interpreter:
    def __init__(self, program: list[Any], ctx: ExecContext):
        self.program = program
        self.ctx = ctx
        self.eval = SafeEvaluator(ctx)

    def run(self) -> None:
        self._exec_block(self.program)

    def _exec_block(self, statements: list[Any]) -> None:
        for stmt in statements:
            if isinstance(stmt, Block):
                self._exec_block_stmt(stmt)
            else:
                self._exec_stmt(stmt)

    def _exec_block_stmt(self, block: Block) -> None:
        if block.kind == "if":
            if self.eval.eval(block.header[0]):
                self._exec_block(block.body)
            elif block.else_body:
                self._exec_block(block.else_body)
            return

        if block.kind == "for":
            name, start_expr, end_expr, step_expr = block.header
            start = self.eval.eval(start_expr)
            end = self.eval.eval(end_expr)
            step = self.eval.eval(step_expr)
            current = start
            compare = (lambda x: x <= end) if step >= 0 else (lambda x: x >= end)
            iterations = 0
            while compare(current):
                iterations += 1
                if iterations > self.ctx.max_loop_iterations:
                    raise QBError("Loop iteration limit exceeded")
                self.ctx.vars[name] = current
                self._exec_block(block.body)
                current += step
            return

        if block.kind == "foreach":
            name, iterable_expr = block.header
            iterable = self.eval.eval(iterable_expr)
            iterations = 0
            for item in iterable:
                iterations += 1
                if iterations > self.ctx.max_loop_iterations:
                    raise QBError("Loop iteration limit exceeded")
                self.ctx.vars[name] = DotDict(item) if isinstance(item, dict) else item
                self._exec_block(block.body)
            return

        raise QBError(f"Unknown block type: {block.kind}")

    def _exec_stmt(self, stmt: str) -> None:
        upper = stmt.upper()

        if upper.startswith("LET ") and "=" in stmt:
            left, expr = stmt[4:].split("=", 1)
            self.ctx.vars[left.strip()] = self.eval.eval(expr.strip())
            return

        if upper.startswith("PRINT "):
            value = self.eval.eval(stmt[6:].strip())
            rendered = str(value)
            self.ctx.output_bytes += len(rendered.encode("utf-8", errors="replace")) + 1
            if self.ctx.output_bytes > self.ctx.max_output_bytes:
                raise QBError("Output limit exceeded")
            self.ctx.output.append(rendered)
            return

        if upper.startswith("HEADER "):
            payload = stmt[7:]
            if "," not in payload:
                raise QBError("HEADER expects: HEADER key, value")
            key_expr, val_expr = payload.split(",", 1)
            key = str(self.eval.eval(key_expr.strip()))
            val = str(self.eval.eval(val_expr.strip()))
            self.ctx.headers.append((key, val))
            return

        if upper.startswith("CGI PARAM ") and " INTO " in upper:
            rhs = stmt[10:]
            left, varname = rhs.split(" INTO ", 1)
            default_val = ""
            if " DEFAULT " in varname.upper():
                idx = varname.upper().index(" DEFAULT ")
                var, d_expr = varname[:idx], varname[idx + 9 :]
                default_val = self.eval.eval(d_expr.strip())
            else:
                var = varname
            key = str(self.eval.eval(left.strip()))
            self.ctx.vars[var.strip()] = self.eval.param(key, default_val)
            return

        if upper.startswith("SQL OPEN "):
            db_path = str(self.eval.eval(stmt[9:].strip()))
            self.ctx.db = sqlite3.connect(db_path)
            self.ctx.db.row_factory = sqlite3.Row
            self.ctx.db.execute("PRAGMA foreign_keys = ON")
            self.ctx.db.execute("PRAGMA busy_timeout = 5000")
            return

        if upper.startswith("SQL EXEC "):
            self._sql_exec(stmt[9:].strip())
            return

        if upper.startswith("SQL QUERY ") and " INTO " in upper:
            payload = stmt[10:]
            idx = payload.upper().rindex(" INTO ")
            query_part = payload[:idx].strip()
            var_name = payload[idx + 6 :].strip()
            rows = self._sql_query(query_part)
            self.ctx.vars[var_name] = [DotDict(r) for r in rows]
            return

        raise QBError(f"Unknown statement: {stmt}")

    def _split_args(self, payload: str) -> list[str]:
        items: list[str] = []
        current: list[str] = []
        in_string = False
        quote_char = ""
        depth = 0

        for ch in payload:
            if in_string:
                current.append(ch)
                if ch == quote_char:
                    in_string = False
                continue

            if ch in ('"', "'"):
                in_string = True
                quote_char = ch
                current.append(ch)
                continue

            if ch in "([":
                depth += 1
                current.append(ch)
                continue
            if ch in ")]":
                depth -= 1
                current.append(ch)
                continue

            if ch == "," and depth == 0:
                items.append("".join(current).strip())
                current = []
            else:
                current.append(ch)

        tail = "".join(current).strip()
        if tail:
            items.append(tail)
        return items

    def _parse_sql_parts(self, payload: str) -> tuple[str, list[Any]]:
        parts = self._split_args(payload)
        if not parts:
            raise QBError("SQL statement requires query expression")
        query = str(self.eval.eval(parts[0]))
        params = [self.eval.eval(p) for p in parts[1:] if p]
        return query, params

    def _sql_exec(self, payload: str) -> None:
        if not self.ctx.db:
            raise QBError("Database not opened. Use SQL OPEN first.")
        query, params = self._parse_sql_parts(payload)
        self.ctx.db.execute(query, params)
        self.ctx.db.commit()

    def _sql_query(self, payload: str) -> list[dict[str, Any]]:
        if not self.ctx.db:
            raise QBError("Database not opened. Use SQL OPEN first.")
        query, params = self._parse_sql_parts(payload)
        cur = self.ctx.db.execute(query, params)
        rows = cur.fetchmany(self.ctx.max_sql_rows + 1)
        if len(rows) > self.ctx.max_sql_rows:
            raise QBError("SQL query row limit exceeded")
        return [dict(row) for row in rows]


def run_script(source: str, *, cgi_mode: bool = False) -> str:
    max_request_bytes = int(os.environ.get("QBCGI_MAX_REQUEST_BYTES", "1048576"))
    max_output_bytes = int(os.environ.get("QBCGI_MAX_OUTPUT_BYTES", "2097152"))
    max_loop_iterations = int(os.environ.get("QBCGI_MAX_LOOP_ITERATIONS", "100000"))
    max_sql_rows = int(os.environ.get("QBCGI_MAX_SQL_ROWS", "10000"))
    params = _parse_cgi_params(max_request_bytes) if cgi_mode else {}
    ctx = ExecContext(
        vars={},
        headers=[],
        output=[],
        db=None,
        cgi_params=params,
        max_output_bytes=max_output_bytes,
        max_loop_iterations=max_loop_iterations,
        max_sql_rows=max_sql_rows,
    )
    program = Parser(source).parse()
    Interpreter(program, ctx).run()

    out = io.StringIO()
    if cgi_mode:
        headers = ctx.headers or [("Content-Type", "text/html; charset=utf-8")]
        headers.extend(
            [
                ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
                ("Referrer-Policy", "no-referrer"),
            ]
        )
        for key, value in headers:
            out.write(f"{key}: {value}\r\n")
        out.write("\r\n")

    out.write("\n".join(ctx.output))
    if ctx.db:
        ctx.db.close()
    return out.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run QBCGI scripts")
    ap.add_argument("script", help="Path to .qbb script")
    ap.add_argument("--cgi", action="store_true", help="Enable CGI request parsing and HTTP headers")
    args = ap.parse_args()

    try:
        with open(args.script, "r", encoding="utf-8") as f:
            source = f.read()
        sys.stdout.write(run_script(source, cgi_mode=args.cgi))
        return 0
    except QBError as exc:
        if args.cgi:
            sys.stdout.write("Status: 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\n")
        debug = os.environ.get("QBCGI_DEBUG_ERRORS", "").lower() in {"1", "true", "yes"}
        if debug:
            sys.stdout.write(f"QBCGI error: {exc}\n")
        else:
            sys.stdout.write("QBCGI error: Internal execution error\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
