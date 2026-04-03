#!/usr/bin/env python3
"""Simple CGI entrypoint for Apache/Nginx + fcgiwrap usage."""
from pathlib import Path
from qbcgi import render_cgi_error_response, run_script

SCRIPT = Path(__file__).with_name("examples").joinpath("guestbook.qbb")

if __name__ == "__main__":
    try:
        print(run_script(SCRIPT.read_text(encoding="utf-8"), cgi_mode=True), end="")
    except Exception as exc:
        print(render_cgi_error_response(exc), end="")
