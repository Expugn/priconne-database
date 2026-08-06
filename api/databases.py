"""Vercel API for discovering and downloading current or historical databases."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HISTORY_PATH = Path("data/history.json")
VALID_REGIONS = {"cn", "tw", "jp"}


def load_history() -> dict:
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def select_entries(history: dict, region: str | None = None) -> list[dict]:
    entries = history.get("entries", [])
    if region:
        entries = [entry for entry in entries if entry.get("region") == region]
    return sorted(
        entries,
        key=lambda entry: (entry.get("region", ""), int(entry.get("version", 0))),
        reverse=True,
    )


def latest_by_region(entries: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for entry in entries:
        latest.setdefault(entry["region"], entry)
    return latest


class handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=300, s-maxage=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        region = query.get("region", [None])[0]
        version = query.get("version", [None])[0]
        download = query.get("download", ["0"])[0].lower() in {"1", "true", "yes"}
        if region and region not in VALID_REGIONS:
            self.send_json(400, {"error": "region must be cn, tw, or jp"})
            return

        history = load_history()
        entries = select_entries(history, region)
        if version:
            entries = [entry for entry in entries if str(entry["version"]) == version]
        selected = entries[0] if entries else None
        if download:
            if selected is None:
                self.send_json(404, {"error": "database version not found"})
                return
            self.send_response(302)
            self.send_header("Location", selected["url"])
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return

        self.send_json(
            200,
            {
                "repository": history.get("repository"),
                "latest": latest_by_region(entries),
                "history": entries,
            },
        )

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
