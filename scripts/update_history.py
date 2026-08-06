#!/usr/bin/env python3
"""Record database releases and prepare newly seen versions for archival."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


REGIONS = ("cn", "tw", "jp")
DEFAULT_REPOSITORY = "SonderXiaoming/priconne-database"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def update_history(root: Path, release_date: str | None = None) -> list[dict[str, str]]:
    history_path = root / "data" / "history.json"
    history = read_json(
        history_path,
        {"format": 1, "repository": DEFAULT_REPOSITORY, "entries": []},
    )
    repository = os.environ.get(
        "GITHUB_REPOSITORY", history.get("repository") or DEFAULT_REPOSITORY
    )
    history["repository"] = repository
    entries = history.setdefault("entries", [])
    known = {
        (entry["region"], str(entry["version"])): entry for entry in entries
    }
    release_date = release_date or datetime.now(timezone.utc).date().isoformat()
    release_dir = root / ".cache" / "releases"
    new_entries: list[dict[str, str]] = []
    release_candidates: list[dict[str, str]] = []

    for region in REGIONS:
        database = root / "data" / f"master_{region}_unhash.db"
        version_document = read_json(root / "data" / f"version_{region}.json", {})
        version = str(version_document.get("version", ""))
        if not database.exists() or not version:
            continue
        entry = known.get((region, version))
        if entry is None:
            tag = f"database-{region}-{version}"
            filename = f"master_{region}_unhash_{version}_{release_date}.db"
            entry = {
                "region": region,
                "version": version,
                "date": release_date,
                "tag": tag,
                "filename": filename,
                "url": (
                    f"https://github.com/{repository}/releases/download/"
                    f"{quote(tag)}/{quote(filename)}"
                ),
            }
            entries.append(entry)
            new_entries.append(entry)
        release_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(database, release_dir / entry["filename"])
        release_candidates.append(entry)

    entries.sort(key=lambda item: (item["region"], int(item["version"])))
    write_json(history_path, history)
    write_json(
        root / ".cache" / "release_candidates.json", release_candidates
    )
    return new_entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--date", help="archive date in YYYY-MM-DD format")
    args = parser.parse_args()
    new_entries = update_history(args.root.resolve(), args.date)
    print(f"Prepared {len(new_entries)} new historical database release(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
