"""Regression tests for the Nginx container entrypoint."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_entrypoint_uses_unix_line_endings():
    entrypoint = (ROOT / "nginx" / "docker-entrypoint.sh").read_bytes()

    assert b"\r" not in entrypoint
    assert b"> /etc/nginx/nginx.conf\n" in entrypoint
