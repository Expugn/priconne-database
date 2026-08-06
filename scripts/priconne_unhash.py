#!/usr/bin/env python3
"""Download and deobfuscate Princess Connect CN, TW, and JP master databases.

The game changes every hashed SQLite identifier when the schema is rebuilt.
This tool transfers known names from readable historical databases, a previous
raw snapshot, and a rainbow mapping into the newest raw database.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
import warnings
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


JP_EXTERNAL_URL = "https://roboninon.win/db/download?compressed=true"
JP_IOS_CDN = "https://prd-priconne-redive.akamaized.net/"
JP_IOS_BASELINE_VERSION = 10070110
JP_CONESHELL = (
    Path(__file__).parents[1]
    / "src"
    / "vendor"
    / "coneshell"
    / "Coneshell_call.exe"
)
TW_IOS_CDN = "https://img-pc.so-net.tw/"
TW_IOS_BASELINE_VERSION = 600009
CN_STATUS_URL = (
    "https://l3-prod-all-gs-gzlj.bilibiligame.net/"
    "source_ini/get_maintenance_status?format=json"
)
CN_DEFAULT_CDN = "l1-prod-patch-gzlj.bilibiligame.net/client_ob_771/"
CN_RES_KEY = "ab00a0a6dd915a052a2ef7fd649083e5"
CN_DEFAULT_APP_VERSION = "11.7.2"
CN_IOS_APPSTORE_URL = "https://itunes.apple.com/lookup?id=1423525213&country=cn"
CN_IOS_BASELINE_VERSION = "202607312107"

HASHED_TABLE_PREFIX = "v1_"
MAPPING_FORMAT = 1


@dataclass(frozen=True)
class Column:
    position: int
    name: str
    declared_type: str
    pk_order: int


@dataclass(frozen=True)
class Table:
    position: int
    name: str
    columns: tuple[Column, ...]
    type_counts: tuple[tuple[str, int], ...]
    pk_count: int
    row_count: int


@dataclass
class Proposal:
    target_table: str
    plain_name: str
    score: float
    source: str
    source_db: Path | None = None
    source_table: str | None = None


def log(message: str) -> None:
    print(message, flush=True)


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def replace_quoted_identifier(sql: str | None, old: str, new: str) -> str | None:
    if sql is None:
        return None
    replacements = (
        ("'" + old.replace("'", "''") + "'", "'" + new.replace("'", "''") + "'"),
        ('"' + old.replace('"', '""') + '"', '"' + new.replace('"', '""') + '"'),
        ("[" + old.replace("]", "]]") + "]", "[" + new.replace("]", "]]") + "]"),
        ("`" + old.replace("`", "``") + "`", "`" + new.replace("`", "``") + "`"),
    )
    for source, destination in replacements:
        sql = sql.replace(source, destination)
    return sql


def is_hashed_table(name: str) -> bool:
    return name.startswith(HASHED_TABLE_PREFIX) and len(name) == 67


def json_load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def rainbow_fingerprints(paths: Iterable[Path]) -> list[dict[str, str]]:
    fingerprints: list[dict[str, str]] = []
    for path in paths:
        digest = "missing"
        if path.exists():
            checksum = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    checksum.update(chunk)
            digest = checksum.hexdigest()
        fingerprints.append({"file": path.name, "sha256": digest})
    return fingerprints


def download(
    url: str, destination: Path, expected_sqlite: bool = False
) -> dict[str, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "priconne-tw-unhash-action/1.0"},
    )
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=destination.name + ".", delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            temporary.open("wb") as handle,
        ):
            headers = dict(response.headers.items())
            shutil.copyfileobj(response, handle)
        if expected_sqlite:
            with temporary.open("rb") as check:
                if check.read(16) != b"SQLite format 3\x00":
                    raise RuntimeError(f"download is not SQLite: {url}")
        os.replace(temporary, destination)
        return headers
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "priconne-tw-unhash-action/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(
        url,
        headers=headers or {"User-Agent": "priconne-unhash-action/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def post_json(url: str, value: Any, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(value).encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def decompress_brotli(source: Path, destination: Path) -> None:
    try:
        import brotli
    except ImportError as error:
        raise RuntimeError(
            "Brotli support is required for the JP external source; "
            "install it with: python -m pip install brotli"
        ) from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_bytes(brotli.decompress(source.read_bytes()))
        with temporary.open("rb") as check:
            if check.read(16) != b"SQLite format 3\x00":
                raise RuntimeError("decompressed JP source is not SQLite")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def validate_database(path: Path, require_readable: bool = False) -> dict[str, int]:
    with closing(sqlite_connect(path)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        columns = sum(
            sum(
                1
                for _row in connection.execute(
                    f"PRAGMA table_info({quote_identifier(table)})"
                )
            )
            for table in tables
        )
    readable_tables = sum(not is_hashed_table(table) for table in tables)
    if require_readable and readable_tables < max(1, int(len(tables) * 0.9)):
        raise RuntimeError(
            f"external JP database is still obfuscated: "
            f"{readable_tables}/{len(tables)} readable tables"
        )
    return {
        "tables": len(tables),
        "columns": columns,
        "readable_tables": readable_tables,
    }


def decrypt_jp_cdb(
    source: Path,
    destination: Path,
    executable: Path = JP_CONESHELL,
) -> dict[str, int]:
    """Decrypt an official JP CDB with the Windows helper used by upstream."""

    if os.name != "nt":
        raise RuntimeError("JP CDB decryption requires a Windows runner")
    executable = executable.resolve()
    if not executable.exists():
        raise RuntimeError(f"Coneshell executable is missing: {executable}")
    if not source.exists():
        raise RuntimeError(f"official JP CDB is missing: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        result = subprocess.run(
            [str(executable), "-cdb", str(source.resolve()), str(temporary)],
            cwd=executable.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(
                f"Coneshell failed with exit code {result.returncode}: {detail}"
            )
        stats = validate_database(temporary)
        os.replace(temporary, destination)
        return stats
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def download_jp_readable_reference(
    url: str,
    archive: Path,
    database: Path,
    official_version: int,
) -> dict[str, int]:
    """Download and validate the versioned readable JP reference."""

    headers = download(url, archive)
    disposition = next(
        (
            value
            for key, value in headers.items()
            if key.lower() == "content-disposition"
        ),
        "",
    )
    match = re.search(r"PriconneMasterDatabase_(\d+)\.db\.br", disposition)
    if not match:
        raise RuntimeError(
            "roboninon did not provide a versioned .db.br filename: "
            f"{disposition!r}"
        )
    external_version = int(match.group(1))
    if external_version != official_version:
        raise RuntimeError(
            f"roboninon JP version {external_version} does not match official "
            f"iOS version {official_version}"
        )
    decompress_brotli(archive, database)
    return validate_database(database, require_readable=True)


def cn_request_headers(app_version: str) -> dict[str, str]:
    return {
        "Accept-Encoding": "gzip",
        "User-Agent": "princessconnectredive/1 CFNetwork/1568 Darwin/24.0.0",
        "X-Unity-Version": "2021.3.20f1c1",
        "APP-VER": app_version,
        "BATTLE-LOGIC-VERSION": "4",
        "BUNDLE-VER": "",
        "DEVICE": "1",
        "DEVICE-NAME": "iPhone",
        "EXCEL-VER": "1.0.0",
        "GRAPHICS-DEVICE-NAME": "Apple GPU",
        "IP-ADDRESS": "10.0.2.15",
        "KEYCHAIN": "",
        "LOCALE": "CN",
        "PLATFORM-OS-VERSION": "iPhone OS 18.0",
        "REGION-CODE": "",
        "RES-KEY": CN_RES_KEY,
        "RES-VER": "10002200",
        "SHORT-UDID": "0",
        "PLATFORM": "1",
        "PLATFORM-ID": "1",
        "CHANNEL-ID": "1",
        "DEVICE-ID": hashlib.md5(b"autopcr").hexdigest(),
        "Content-Type": "application/json",
    }


def fetch_cn_app_version() -> str:
    try:
        payload = fetch_json(CN_IOS_APPSTORE_URL)
        results = payload.get("results") or []
        if results and results[0].get("version"):
            return str(results[0]["version"])
    except Exception as error:
        log(f"Unable to read the CN App Store version; using fallback: {error}")
    return CN_DEFAULT_APP_VERSION


def fetch_cn_status(app_version: str) -> tuple[dict[str, Any], str]:
    payload: dict[str, Any] = {}
    for _attempt in range(2):
        payload = post_json(
            CN_STATUS_URL,
            {"viewer_id": "0"},
            cn_request_headers(app_version),
        )
        data = payload.get("data") or {}
        if data.get("manifest_ver") and data.get("resource"):
            return data, app_version
        store_url = str((payload.get("data_headers") or {}).get("store_url", ""))
        match = re.search(r"\d+\.\d+\.\d+", store_url)
        if not match or match.group(0) == app_version:
            break
        app_version = match.group(0)
    data = payload.get("data") or {}
    raise RuntimeError(
        "official CN status response has no manifest version/resources: "
        f"{data.get('server_error') or payload.get('data_headers')}"
    )


def normalize_cdn(value: str) -> str:
    value = value.strip()
    if not value.startswith(("https://", "http://")):
        value = "https://" + value
    return value.rstrip("/") + "/"


def parse_cn_asset_line(line: str) -> dict[str, Any]:
    fields = line.strip().split(",")
    if len(fields) < 4:
        raise RuntimeError(f"invalid CN asset manifest line: {line!r}")
    # New CN manifests contain both a content MD5 and a shorter storage hash.
    # Older manifests use the MD5 for both fields.
    has_storage_hash = len(fields) >= 6
    md5 = fields[1]
    storage_hash = fields[2] if has_storage_hash else md5
    size_index = 4 if has_storage_hash else 3
    return {
        "path": fields[0],
        "md5": md5,
        "storage_hash": storage_hash,
        "size": int(fields[size_index]),
    }


def probe_cn_build(
    version: str,
    resources: list[str],
    platforms: tuple[str, ...] = ("iOS",),
) -> dict[str, Any] | None:
    for resource in resources:
        cdn = normalize_cdn(resource)
        for platform in platforms:
            root = f"{cdn}Manifest/AssetBundles/{platform}/{version}/"
            try:
                manifest = fetch_text(root + "manifest/manifest_assetmanifest")
                master_path = next(
                    line.split(",", 1)[0]
                    for line in manifest.splitlines()
                    if "masterdata" in line.lower()
                    and "masterdata_assetmanifest_s" not in line.lower()
                )
                asset = parse_cn_asset_line(fetch_text(root + master_path))
                return {
                    "version": str(version),
                    "platform": platform,
                    "cdn": cdn,
                    **asset,
                }
            except Exception:
                continue
    return None


def probe_ios_build(
    version: int | str,
    cdn: str,
    version_width: int = 0,
) -> dict[str, Any] | None:
    version_text = str(version).zfill(version_width)
    root = (
        f"{normalize_cdn(cdn)}dl/Resources/{version_text}/"
        "Jpn/AssetBundles/iOS/"
    )
    try:
        manifest = fetch_text(root + "manifest/manifest_assetmanifest")
        master_path = next(
            line.split(",", 1)[0]
            for line in manifest.splitlines()
            if "masterdata" in line.lower()
            and "masterdata_assetmanifest_s" not in line.lower()
        )
        asset_manifest = fetch_text(root + master_path)
        asset_line = next(
            line
            for line in asset_manifest.splitlines()
            if "masterdata_master" in line.lower()
        )
        return {
            "version": version_text,
            "platform": "iOS",
            "cdn": normalize_cdn(cdn),
            **parse_cn_asset_line(asset_line),
        }
    except Exception:
        return None


def discover_tw_build(current_version: dict[str, Any]) -> dict[str, Any]:
    latest = int(current_version.get("version") or TW_IOS_BASELINE_VERSION)
    build = probe_ios_build(latest, TW_IOS_CDN, version_width=8)
    if build is None and latest != TW_IOS_BASELINE_VERSION:
        latest = TW_IOS_BASELINE_VERSION
        build = probe_ios_build(latest, TW_IOS_CDN, version_width=8)
    if build is None:
        raise RuntimeError("TW iOS baseline manifest is unavailable")

    # TW versions normally advance by one, but occasionally jump to a new
    # decimal boundary. Probe only the official iOS CDN around those boundaries.
    for delta in (1_000_000, 100_000, 10_000, 1_000, 100, 10, 1):
        while True:
            base = ((latest // delta) + 1) * delta if delta > 1 else latest + 1
            found = None
            for offset in range(5 if delta > 1 else 1):
                candidate = base + offset
                candidate_build = probe_ios_build(
                    candidate, TW_IOS_CDN, version_width=8
                )
                if candidate_build is not None:
                    found = candidate_build
                    latest = candidate
                    break
            if found is None:
                break
            build = found
    return build


def discover_jp_build(current_version: dict[str, Any]) -> dict[str, Any]:
    latest = int(current_version.get("version") or JP_IOS_BASELINE_VERSION)
    build = probe_ios_build(latest, JP_IOS_CDN)
    if build is None and latest != JP_IOS_BASELINE_VERSION:
        latest = JP_IOS_BASELINE_VERSION
        build = probe_ios_build(latest, JP_IOS_CDN)
    if build is None:
        raise RuntimeError("JP iOS baseline manifest is unavailable")

    misses = 0
    candidate = latest + 10
    while misses < 20:
        candidate_build = probe_ios_build(candidate, JP_IOS_CDN)
        if candidate_build is not None:
            build = candidate_build
            latest = candidate
            misses = 0
        else:
            misses += 1
        candidate += 10
    return build


def download_standard_ios_asset(build: dict[str, Any], destination: Path) -> None:
    storage_hash = build["storage_hash"]
    asset_url = (
        f"{build['cdn']}dl/pool/AssetBundles/"
        f"{storage_hash[:2]}/{storage_hash}"
    )
    download(asset_url, destination)
    actual_md5 = hashlib.md5(destination.read_bytes()).hexdigest()
    if actual_md5 != build["md5"]:
        raise RuntimeError(
            f"iOS bundle MD5 mismatch: expected {build['md5']}, got {actual_md5}"
        )
    if destination.stat().st_size != int(build["size"]):
        raise RuntimeError(
            f"iOS bundle size mismatch: expected {build['size']}, "
            f"got {destination.stat().st_size}"
        )


def discover_cn_build(
    display_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, str], str]:
    app_version = fetch_cn_app_version()
    sources: dict[str, str] = {}
    resources = [CN_DEFAULT_CDN]
    official_version: str | None = None
    try:
        status, app_version = fetch_cn_status(app_version)
        official_version = str(status["manifest_ver"])
        sources["official-ios"] = official_version
        resources = list(status["resource"])
    except Exception as error:
        log(f"Official CN version query unavailable: {error}")

    ios_candidates = (
        ("user-override", display_version),
        ("official-ios", official_version),
        ("ios-baseline", CN_IOS_BASELINE_VERSION),
    )
    candidates: list[str] = []
    for label, value in ios_candidates:
        if value:
            value = str(value)
            sources[label] = value
            candidates.append(value)

    for candidate in sorted(set(candidates), key=int, reverse=True):
        build = probe_cn_build(candidate, resources, ("iOS",))
        if build:
            build["version_sources"] = dict(sorted(sources.items()))
            return build, sources, app_version
    raise RuntimeError("no CN iOS candidate points to a downloadable manifest")


def extract_unity_database(bundle_path: Path, database_path: Path) -> None:
    try:
        import UnityPy
        import UnityPy.config
        from UnityPy.exceptions import UnityVersionFallbackWarning
    except ImportError as error:
        raise RuntimeError(
            "UnityPy is required for CN database extraction; "
            "install it with: python -m pip install UnityPy"
        ) from error
    UnityPy.config.FALLBACK_UNITY_VERSION = "2021.3.20f1"
    raw_database: bytes | None = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnityVersionFallbackWarning)
        environment = UnityPy.load(str(bundle_path))
        for obj in environment.objects:
            if obj.type.name != "TextAsset":
                continue
            data = obj.read()
            value = data.m_Script
            raw = (
                value.encode("utf-8", errors="surrogateescape")
                if isinstance(value, str)
                else bytes(value)
            )
            if raw.startswith(b"SQLite format 3\x00"):
                raw_database = raw
                break
    if raw_database is None:
        raise RuntimeError("CN Unity bundle contains no SQLite TextAsset")
    temporary = database_path.with_suffix(database_path.suffix + ".tmp")
    temporary.write_bytes(raw_database)
    os.replace(temporary, database_path)


def sqlite_connect(path: Path, readonly: bool = True) -> sqlite3.Connection:
    if readonly:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def declared_affinity(value: str) -> str:
    value = (value or "").upper()
    if "INT" in value:
        return "INTEGER"
    if any(token in value for token in ("CHAR", "CLOB", "TEXT")):
        return "TEXT"
    if "BLOB" in value or not value:
        return "BLOB"
    if any(token in value for token in ("REAL", "FLOA", "DOUB")):
        return "REAL"
    return "NUMERIC"


def inspect_database(path: Path) -> list[Table]:
    result: list[Table] = []
    with closing(sqlite_connect(path)) as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
            )
        ]
        for position, name in enumerate(names):
            raw_columns = list(
                connection.execute(f"PRAGMA table_info({quote_identifier(name)})")
            )
            columns = tuple(
                Column(
                    position=row[0],
                    name=row[1],
                    declared_type=declared_affinity(row[2]),
                    pk_order=int(row[5] or 0),
                )
                for row in raw_columns
            )
            type_counts = tuple(
                sorted(Counter(column.declared_type for column in columns).items())
            )
            row_count = connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(name)}"
            ).fetchone()[0]
            result.append(
                Table(
                    position=position,
                    name=name,
                    columns=columns,
                    type_counts=type_counts,
                    pk_count=sum(column.pk_order > 0 for column in columns),
                    row_count=row_count,
                )
            )
    return result


def table_similarity(left: Table, right: Table) -> float:
    left_count = len(left.columns)
    right_count = len(right.columns)
    score = 9.0 if left_count == right_count else -min(
        18.0, abs(left_count - right_count) * 1.5
    )

    if left.type_counts == right.type_counts:
        score += 5.0
    else:
        left_types = dict(left.type_counts)
        right_types = dict(right.type_counts)
        difference = sum(
            abs(left_types.get(key, 0) - right_types.get(key, 0))
            for key in left_types.keys() | right_types.keys()
        )
        score += max(-5.0, 3.0 - 8.0 * difference / max(left_count, right_count, 1))

    score += 2.0 if left.pk_count == right.pk_count else -2.0
    if left.row_count == right.row_count:
        score += 7.0
    elif not left.row_count or not right.row_count:
        score -= 1.0
    else:
        score += 6.0 * min(left.row_count, right.row_count) / max(
            left.row_count, right.row_count
        ) - 2.0
    return score


def align_tables(
    source: list[Table], target: list[Table], minimum_score: float = 8.0
) -> list[tuple[Table, Table, float]]:
    """Weighted global sequence alignment.

    Cygames randomizes identifiers and column order, but table creation order is
    highly stable. A sequence alignment tolerates inserted and removed tables.
    """

    gap = -3.0
    source_count = len(source)
    target_count = len(target)
    previous = [index * gap for index in range(target_count + 1)]
    trace = [bytearray(target_count + 1) for _ in range(source_count + 1)]
    for column in range(1, target_count + 1):
        trace[0][column] = 2

    for row in range(1, source_count + 1):
        current = [row * gap] + [0.0] * target_count
        trace[row][0] = 1
        for column in range(1, target_count + 1):
            choices = (
                previous[column - 1]
                + table_similarity(source[row - 1], target[column - 1]),
                previous[column] + gap,
                current[column - 1] + gap,
            )
            direction = max(range(3), key=choices.__getitem__)
            current[column] = choices[direction]
            trace[row][column] = direction
        previous = current

    pairs: list[tuple[Table, Table, float]] = []
    row = source_count
    column = target_count
    while row or column:
        direction = trace[row][column]
        if direction == 0:
            score = table_similarity(source[row - 1], target[column - 1])
            if score >= minimum_score:
                pairs.append((source[row - 1], target[column - 1], score))
            row -= 1
            column -= 1
        elif direction == 1:
            row -= 1
        else:
            column -= 1
    pairs.reverse()
    return pairs


def normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 10)
    if isinstance(value, bytes):
        return ("bytes", hashlib.sha256(value).hexdigest())
    return value


def sample_rows(
    connection: sqlite3.Connection,
    table: Table,
    pk_columns: list[Column],
    limit: int = 256,
) -> dict[tuple[Any, ...], tuple[Any, ...]]:
    if not pk_columns:
        return {}
    order = ", ".join(
        quote_identifier(column.name)
        for column in sorted(pk_columns, key=lambda item: item.pk_order)
    )
    query = (
        f"SELECT * FROM {quote_identifier(table.name)} "
        f"ORDER BY {order} LIMIT {int(limit)}"
    )
    pk_positions = [column.position for column in sorted(pk_columns, key=lambda x: x.pk_order)]
    rows: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for raw in connection.execute(query):
        row = tuple(normalize_value(value) for value in raw)
        key = tuple(row[position] for position in pk_positions)
        rows[key] = row
    return rows


def match_columns(
    source_db: Path,
    source_table: Table,
    target_db: Path,
    target_table: Table,
) -> dict[str, str]:
    """Match shuffled columns by PK metadata and values on shared records."""

    mapping: dict[str, str] = {}
    source_pk = sorted(
        (column for column in source_table.columns if column.pk_order),
        key=lambda item: item.pk_order,
    )
    target_pk = sorted(
        (column for column in target_table.columns if column.pk_order),
        key=lambda item: item.pk_order,
    )
    if len(source_pk) == len(target_pk):
        for source_column, target_column in zip(source_pk, target_pk):
            mapping[target_column.name] = source_column.name

    if not source_pk or len(source_pk) != len(target_pk):
        return mapping

    with closing(sqlite_connect(source_db)) as source_connection, closing(
        sqlite_connect(target_db)
    ) as target_connection:
        source_rows = sample_rows(source_connection, source_table, source_pk)
        target_rows = sample_rows(target_connection, target_table, target_pk)

    shared_keys = list(source_rows.keys() & target_rows.keys())
    if len(shared_keys) < 3:
        return mapping

    used_source = set(mapping.values())
    used_target = set(mapping.keys())
    candidates: list[tuple[float, str, str]] = []
    for source_column in source_table.columns:
        if source_column.name in used_source:
            continue
        for target_column in target_table.columns:
            if target_column.name in used_target:
                continue
            if source_column.declared_type != target_column.declared_type:
                continue
            equal = 0
            informative = 0
            for key in shared_keys:
                left = source_rows[key][source_column.position]
                right = target_rows[key][target_column.position]
                if left == right:
                    equal += 1
                if left not in (None, 0, 0.0, "", b""):
                    informative += 1
            ratio = equal / len(shared_keys)
            if ratio >= 0.985 and informative:
                score = ratio * 100.0 + min(informative, 20) / 20.0
                candidates.append((score, target_column.name, source_column.name))

    # Mutual-best greedy matching avoids assigning constant columns arbitrarily.
    candidates.sort(reverse=True)
    best_for_target: dict[str, tuple[float, str]] = {}
    best_for_source: dict[str, tuple[float, str]] = {}
    for score, target_name, source_name in candidates:
        best_for_target.setdefault(target_name, (score, source_name))
        best_for_source.setdefault(source_name, (score, target_name))
    for target_name, (score, source_name) in best_for_target.items():
        if best_for_source.get(source_name, (None, None))[1] == target_name:
            mapping[target_name] = source_name
    return mapping


def load_rainbows(
    paths: Path | list[Path],
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, dict[str, str]]]:
    if isinstance(paths, Path):
        paths = [paths]
    sources: list[tuple[str, dict[str, Any]]] = []
    by_name: dict[str, dict[str, str]] = {}
    for path in paths:
        raw = json_load(path, {}) or {}
        sources.append((path.name, raw))
        for _hashed_table, columns in raw.items():
            if not isinstance(columns, dict) or "--table_name" not in columns:
                continue
            plain_name = columns["--table_name"]
            by_name.setdefault(
                plain_name,
                {
                    key: value
                    for key, value in columns.items()
                    if key != "--table_name"
                },
            )
    return sources, by_name


def type_hints(reference_paths: Iterable[Path]) -> dict[str, str]:
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for path in reference_paths:
        for table in inspect_database(path):
            if is_hashed_table(table.name):
                continue
            for column in table.columns:
                votes[column.name][column.declared_type] += 1
    return {
        name: counter.most_common(1)[0][0]
        for name, counter in votes.items()
        if counter
    }


def supplement_columns_from_rainbow(
    table: Table,
    table_name: str,
    columns: dict[str, str],
    rainbow_by_name: dict[str, dict[str, str]],
    hints: dict[str, str],
) -> None:
    entry = rainbow_by_name.get(table_name)
    if not entry:
        return
    available_names = set(entry.values()) - set(columns.values())
    available_columns = [column for column in table.columns if column.name not in columns]
    if len(available_names) != len(available_columns):
        return

    # Repeatedly assign type groups that contain exactly one column and one name.
    progress = True
    while progress:
        progress = False
        for affinity in ("INTEGER", "TEXT", "REAL", "NUMERIC", "BLOB"):
            target_group = [
                column
                for column in available_columns
                if column.declared_type == affinity and column.name not in columns
            ]
            name_group = [
                name
                for name in available_names
                if name not in columns.values() and hints.get(name) == affinity
            ]
            if len(target_group) == len(name_group) == 1:
                columns[target_group[0].name] = name_group[0]
                progress = True
    remaining_columns = [column for column in available_columns if column.name not in columns]
    remaining_names = available_names - set(columns.values())
    if len(remaining_columns) == len(remaining_names) == 1:
        columns[remaining_columns[0].name] = next(iter(remaining_names))


def previous_proposals(
    previous_db: Path,
    previous_mapping: dict[str, Any],
    target_tables: list[Table],
) -> list[Proposal]:
    if not previous_db.exists() or not previous_mapping:
        return []
    previous_tables = inspect_database(previous_db)
    mapping_tables = previous_mapping.get("tables", {})
    result: list[Proposal] = []
    for source, target, score in align_tables(previous_tables, target_tables):
        known = mapping_tables.get(source.name)
        if not known:
            continue
        result.append(
            Proposal(
                target_table=target.name,
                plain_name=known["name"],
                score=100.0 + score,
                source="previous",
                source_db=previous_db,
                source_table=source.name,
            )
        )
    return result


def resolve_mapping(
    target_db: Path,
    rainbow_paths: Path | list[Path],
    references: list[tuple[str, Path, int]],
    previous_db: Path | None = None,
    previous_mapping_path: Path | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_tables = inspect_database(target_db)
    target_by_name = {table.name: table for table in target_tables}
    normalized_rainbow_paths = (
        [rainbow_paths] if isinstance(rainbow_paths, Path) else rainbow_paths
    )
    rainbow_sources, rainbow_by_name = load_rainbows(normalized_rainbow_paths)
    previous_mapping = (
        json_load(previous_mapping_path, {}) if previous_mapping_path else {}
    ) or {}

    proposals: list[Proposal] = []
    if previous_db and previous_mapping:
        proposals.extend(
            previous_proposals(previous_db, previous_mapping, target_tables)
        )

    # Direct hash hits are definitive when a rainbow file matches this build.
    direct_by_table: dict[str, tuple[dict[str, str], str]] = {}
    for table in target_tables:
        for priority, (label, rainbow_raw) in enumerate(rainbow_sources):
            direct = rainbow_raw.get(table.name)
            if direct and "--table_name" in direct:
                source = f"rainbow-direct:{label}"
                direct_by_table[table.name] = (direct, source)
                proposals.append(
                    Proposal(
                        table.name,
                        direct["--table_name"],
                        200.0 - priority,
                        source,
                    )
                )
                break

    reference_tables: dict[Path, dict[str, Table]] = {}
    for label, path, priority in references:
        tables = inspect_database(path)
        reference_tables[path] = {table.name: table for table in tables}
        for source, target, alignment_score in align_tables(tables, target_tables):
            if is_hashed_table(source.name):
                continue
            proposals.append(
                Proposal(
                    target_table=target.name,
                    plain_name=source.name,
                    score=priority + alignment_score,
                    source=label,
                    source_db=path,
                    source_table=source.name,
                )
            )

    # Aggregate independent agreement, then enforce a one-to-one table mapping.
    grouped: dict[tuple[str, str], list[Proposal]] = defaultdict(list)
    for proposal in proposals:
        grouped[(proposal.target_table, proposal.plain_name)].append(proposal)
    ranked: list[tuple[float, str, str, list[Proposal]]] = []
    for (target_name, plain_name), group in grouped.items():
        best = max(group, key=lambda item: item.score)
        agreement_bonus = 8.0 * (len({item.source for item in group}) - 1)
        ranked.append((best.score + agreement_bonus, target_name, plain_name, group))
    ranked.sort(reverse=True)

    assigned_targets: set[str] = set()
    assigned_names: set[str] = set()
    chosen: dict[str, tuple[str, float, list[Proposal]]] = {}
    for score, target_name, plain_name, group in ranked:
        if target_name in assigned_targets or plain_name in assigned_names:
            continue
        chosen[target_name] = (plain_name, score, group)
        assigned_targets.add(target_name)
        assigned_names.add(plain_name)

    reference_paths = [path for _, path, _ in references]
    hints = type_hints(reference_paths)
    output_tables: dict[str, Any] = {}
    previous_tables = previous_mapping.get("tables", {})
    previous_lookup = {table.name: table for table in inspect_database(previous_db)} if previous_db and previous_db.exists() else {}

    for target_hash, (plain_name, score, group) in chosen.items():
        target_table = target_by_name[target_hash]
        column_votes: dict[tuple[str, str], tuple[float, str]] = {}

        direct, direct_source = direct_by_table.get(target_hash, ({}, ""))
        for hashed_column, plain_column in direct.items():
            if hashed_column != "--table_name":
                column_votes[(hashed_column, plain_column)] = (300.0, direct_source)

        # The best reference normally contains every transferable column. Reading
        # every agreeing database again is expensive and adds little confidence.
        for proposal in sorted(group, key=lambda item: item.score, reverse=True)[:1]:
            if proposal.source == "previous" and previous_db and proposal.source_table:
                source_table = previous_lookup.get(proposal.source_table)
                source_known = previous_tables.get(proposal.source_table, {})
                if source_table and source_known:
                    transferred = match_columns(
                        previous_db, source_table, target_db, target_table
                    )
                    old_columns = source_known.get("columns", {})
                    for new_hash, old_hash in transferred.items():
                        plain_column = old_columns.get(old_hash)
                        if plain_column:
                            column_votes[(new_hash, plain_column)] = (
                                proposal.score,
                                "previous",
                            )
            elif proposal.source_db and proposal.source_table:
                source_table = reference_tables[proposal.source_db].get(
                    proposal.source_table
                )
                if source_table:
                    transferred = match_columns(
                        proposal.source_db, source_table, target_db, target_table
                    )
                    for hashed_column, plain_column in transferred.items():
                        key = (hashed_column, plain_column)
                        if key not in column_votes or column_votes[key][0] < proposal.score:
                            column_votes[key] = (proposal.score, proposal.source)

        # Resolve column conflicts one-to-one.
        columns: dict[str, str] = {}
        used_plain: set[str] = set()
        for (hashed_column, plain_column), (column_score, _) in sorted(
            column_votes.items(), key=lambda item: item[1][0], reverse=True
        ):
            if hashed_column in columns or plain_column in used_plain:
                continue
            if hashed_column not in {column.name for column in target_table.columns}:
                continue
            columns[hashed_column] = plain_column
            used_plain.add(plain_column)

        supplement_columns_from_rainbow(
            target_table, plain_name, columns, rainbow_by_name, hints
        )
        output_tables[target_hash] = {
            "name": plain_name,
            "confidence": round(score, 3),
            "sources": sorted({proposal.source for proposal in group}),
            "columns": dict(sorted(columns.items())),
        }

    mapped_columns = sum(len(value["columns"]) for value in output_tables.values())
    total_columns = sum(len(table.columns) for table in target_tables)
    return {
        "format": MAPPING_FORMAT,
        "source": source_metadata or {},
        "rainbows": rainbow_fingerprints(normalized_rainbow_paths),
        "summary": {
            "tables_total": len(target_tables),
            "tables_mapped": len(output_tables),
            "columns_total": total_columns,
            "columns_mapped": mapped_columns,
        },
        "tables": dict(sorted(output_tables.items())),
    }


def deobfuscate_database(
    raw_db: Path, output_db: Path, mapping: dict[str, Any]
) -> dict[str, Any]:
    output_db.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_db.with_suffix(output_db.suffix + ".tmp")
    shutil.copy2(raw_db, temporary)
    renamed_tables = 0
    renamed_columns = 0
    skipped: list[str] = []

    try:
        # Thousands of ALTER TABLE statements take several minutes because each
        # one reparses the complete schema. Updating sqlite_schema in one
        # transaction is equivalent for identifier-only changes and takes less
        # than a second. We immediately reopen and integrity-check the result.
        with closing(sqlite_connect(temporary, readonly=False)) as connection:
            existing_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )
            }
            connection.execute("PRAGMA writable_schema=ON")
            for hashed_table, value in mapping.get("tables", {}).items():
                if hashed_table not in existing_tables:
                    continue
                plain_table = value["name"]
                if plain_table in existing_tables and plain_table != hashed_table:
                    skipped.append(f"table collision: {plain_table}")
                    continue

                table_row = connection.execute(
                    "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?",
                    (hashed_table,),
                ).fetchone()
                if not table_row or not table_row[0]:
                    continue
                table_sql = table_row[0]
                current_columns = {
                    row[1]
                    for row in connection.execute(
                        f"PRAGMA table_info({quote_identifier(hashed_table)})"
                    )
                }
                accepted_columns: dict[str, str] = {}
                for hashed_column, plain_column in value.get("columns", {}).items():
                    if hashed_column not in current_columns:
                        continue
                    if plain_column in current_columns and plain_column != hashed_column:
                        skipped.append(f"column collision: {plain_table}.{plain_column}")
                        continue
                    accepted_columns[hashed_column] = plain_column
                    current_columns.remove(hashed_column)
                    current_columns.add(plain_column)

                dependencies = list(
                    connection.execute(
                        "SELECT rowid, type, name, sql FROM sqlite_schema "
                        "WHERE tbl_name=? AND type IN ('index', 'trigger')",
                        (hashed_table,),
                    )
                )
                for hashed_column, plain_column in accepted_columns.items():
                    table_sql = replace_quoted_identifier(
                        table_sql, hashed_column, plain_column
                    )
                table_sql = replace_quoted_identifier(
                    table_sql, hashed_table, plain_table
                )
                connection.execute(
                    "UPDATE sqlite_schema SET name=?, tbl_name=?, sql=? "
                    "WHERE type='table' AND name=?",
                    (plain_table, plain_table, table_sql, hashed_table),
                )

                autoindex_prefix = f"sqlite_autoindex_{hashed_table}_"
                for rowid, _dependency_type, dependency_name, dependency_sql in dependencies:
                    for hashed_column, plain_column in accepted_columns.items():
                        dependency_sql = replace_quoted_identifier(
                            dependency_sql, hashed_column, plain_column
                        )
                    dependency_sql = replace_quoted_identifier(
                        dependency_sql, hashed_table, plain_table
                    )
                    if dependency_name.startswith(autoindex_prefix):
                        suffix = dependency_name[len(autoindex_prefix) :]
                        dependency_name = f"sqlite_autoindex_{plain_table}_{suffix}"
                    connection.execute(
                        "UPDATE sqlite_schema SET name=?, tbl_name=?, sql=? WHERE rowid=?",
                        (dependency_name, plain_table, dependency_sql, rowid),
                    )

                existing_tables.remove(hashed_table)
                existing_tables.add(plain_table)
                renamed_tables += 1
                renamed_columns += len(accepted_columns)

            schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
            connection.execute(f"PRAGMA schema_version={schema_version + 1}")
            connection.execute("PRAGMA writable_schema=OFF")
            connection.commit()

        with closing(sqlite_connect(temporary)) as check:
            # Reading sqlite_schema forces SQLite to parse every modified entry.
            list(check.execute("SELECT type, name, tbl_name FROM sqlite_schema"))
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        os.replace(temporary, output_db)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "renamed_tables": renamed_tables,
        "renamed_columns": renamed_columns,
        "skipped": skipped,
        "integrity_check": "ok",
    }


def build_report(
    mapping: dict[str, Any], rename: dict[str, Any], region: str = "TW"
) -> str:
    summary = mapping["summary"]
    table_percent = 100 * summary["tables_mapped"] / max(summary["tables_total"], 1)
    column_percent = 100 * summary["columns_mapped"] / max(summary["columns_total"], 1)
    source = mapping.get("source", {})
    return "\n".join(
        (
            f"# {region} 数据库自动反混淆报告",
            "",
            f"- 来源版本：`{source.get('version', 'unknown')}`",
            f"- 官方资源哈希：`{source.get('hash', 'unknown')}`",
            f"- 表名覆盖：{summary['tables_mapped']} / {summary['tables_total']} "
            f"({table_percent:.1f}%)",
            f"- 字段名覆盖：{summary['columns_mapped']} / {summary['columns_total']} "
            f"({column_percent:.1f}%)",
            f"- 实际重命名：{rename['renamed_tables']} 张表、"
            f"{rename['renamed_columns']} 个字段",
            f"- SQLite 完整性检查：`{rename['integrity_check']}`",
            "",
            "> 未识别的表或字段会保留原哈希名，绝不会猜名覆盖。",
            "",
        )
    )


def build_external_report(
    region: str,
    source: dict[str, Any],
    stats: dict[str, int],
    source_url: str,
) -> str:
    return "\n".join(
        (
            f"# {region} 数据库自动恢复报告",
            "",
            f"- 来源版本：`{source.get('version', 'unknown')}`",
            f"- 官方资源哈希：`{source.get('hash', 'unknown')}`",
            f"- 恢复来源：`{source_url}`",
            f"- 可读表：{stats['readable_tables']} / {stats['tables']}",
            f"- 字段总数：{stats['columns']}",
            "- SQLite 完整性检查：`ok`",
            "",
        )
    )


def parse_reference(value: str) -> tuple[str, str, int]:
    parts = value.split("=", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("reference must be LABEL=PATH_OR_URL=PRIORITY")
    try:
        priority = int(parts[2])
    except ValueError as error:
        raise argparse.ArgumentTypeError("reference priority must be an integer") from error
    return parts[0], parts[1], priority


def update_command(args: argparse.Namespace) -> int:
    output_dir = args.output_dir.resolve()
    cache_dir = args.cache_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    current_version_path = output_dir / "version_tw.json"
    current_version = json_load(current_version_path, {}) or {}
    mapping_path = cache_dir / "mapping_tw.json"
    current_mapping = json_load(mapping_path, {}) or {}
    rainbow_paths = args.rainbow or [Path("rainbow_tw.json")]
    resolved_rainbows = [path.resolve() for path in rainbow_paths]
    current_rainbows = rainbow_fingerprints(resolved_rainbows)
    output_db = output_dir / "master_tw_unhash.db"
    build = discover_tw_build(current_version)
    source_metadata = {
        "version": int(build["version"]),
        "hash": build["storage_hash"],
        "asset_md5": build["md5"],
        "storage_hash": build["storage_hash"],
        "platform": "iOS",
        "cdn": build["cdn"],
    }
    raw_db = cache_dir / "master_tw_latest.db"
    previous_db = cache_dir / "master_tw_previous.db"
    if (
        not args.force
        and current_version.get("hash") == build["storage_hash"]
        and current_mapping.get("rainbows") == current_rainbows
        and output_db.exists()
    ):
        log(f"TW database is already current: {build['version']}")
        return 0

    if raw_db.exists():
        shutil.copy2(raw_db, previous_db)
    bundle_path = cache_dir / "master_tw_latest.unity3d"
    candidate_db = cache_dir / "master_tw_candidate.db"
    log(f"Downloading TW database {build['version']} from official iOS CDN")
    download_standard_ios_asset(build, bundle_path)
    extract_unity_database(bundle_path, candidate_db)
    validate_database(candidate_db)
    os.replace(candidate_db, raw_db)

    previous_mapping_path = mapping_path if mapping_path.exists() else None
    usable_previous_db = (
        previous_db
        if previous_db.exists() and previous_mapping_path is not None
        else None
    )
    references: list[tuple[str, Path, int]] = []
    if output_db.exists():
        references.append(("tw-previous-readable", output_db, 130))
    for label, location, priority in args.reference or []:
        if location.startswith(("https://", "http://")):
            reference_path = cache_dir / "references" / f"{label}.db"
            if not reference_path.exists():
                log(f"Downloading reference {label}")
                download(location, reference_path, expected_sqlite=True)
        else:
            reference_path = Path(location).resolve()
        references.append((label, reference_path, priority))

    log("Resolving table and column names")
    mapping = resolve_mapping(
        target_db=raw_db,
        rainbow_paths=resolved_rainbows,
        references=references,
        previous_db=usable_previous_db,
        previous_mapping_path=previous_mapping_path,
        source_metadata=source_metadata,
    )
    json_write(mapping_path, mapping)

    rename = deobfuscate_database(raw_db, output_db, mapping)
    json_write(current_version_path, source_metadata)
    report = build_report(mapping, rename)
    (cache_dir / "REPORT_tw.md").write_text(report, encoding="utf-8")
    log(report)
    return 0


def update_jp_command(args: argparse.Namespace) -> int:
    output_dir = args.output_dir.resolve()
    cache_dir = args.cache_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    output_db = output_dir / "master_jp_unhash.db"
    version_path = output_dir / "version_jp.json"
    report_path = cache_dir / "REPORT_jp.md"
    mapping_path = cache_dir / "mapping_jp.json"
    raw_db = cache_dir / "master_jp_latest_raw.db"
    previous_raw_db = cache_dir / "master_jp_previous_raw.db"
    current_version = json_load(version_path, {}) or {}
    build = discover_jp_build(current_version)
    official_version = int(build["version"])
    source_metadata = {
        "version": official_version,
        "hash": build["storage_hash"],
        "asset_md5": build["md5"],
        "storage_hash": build["storage_hash"],
        "platform": "iOS",
        "cdn": build["cdn"],
        "source": "official-ios-cdn+coneshell",
        "name_reference_priority": ["roboninon", "jp-previous-readable"],
    }
    if (
        not args.force
        and current_version.get("version") == official_version
        and current_version.get("hash") == build["storage_hash"]
        and output_db.exists()
        and raw_db.exists()
        and mapping_path.exists()
    ):
        log(f"JP database is already current: {official_version}")
        return 0

    official_asset = cache_dir / "master_jp_official.cdb"
    expected_md5 = str(build["md5"])
    expected_size = int(build["size"])
    cached_asset_ok = (
        official_asset.exists()
        and official_asset.stat().st_size == expected_size
        and hashlib.md5(official_asset.read_bytes()).hexdigest() == expected_md5
    )
    if cached_asset_ok:
        log(f"Using cached official JP CDB {official_version}")
    else:
        log(f"Downloading JP database {official_version} from official iOS CDN")
        download_standard_ios_asset(build, official_asset)

    # roboninon has the highest priority for both name recovery and fallback.
    external_archive = cache_dir / "jp_external.db.br"
    external_database = cache_dir / "jp_external.db"
    external_stats: dict[str, int] | None = None
    external_error: Exception | None = None
    try:
        log("Downloading the highest-priority JP name reference from roboninon")
        external_stats = download_jp_readable_reference(
            args.external_url,
            external_archive,
            external_database,
            official_version,
        )
    except Exception as error:
        external_error = error
        log(f"JP roboninon reference unavailable or invalid: {error}")

    previous_mapping_path = mapping_path if mapping_path.exists() else None
    if raw_db.exists() and previous_mapping_path is not None:
        shutil.copy2(raw_db, previous_raw_db)
    usable_previous_raw = (
        previous_raw_db
        if previous_raw_db.exists() and previous_mapping_path is not None
        else None
    )
    candidate_raw = cache_dir / "master_jp_candidate_raw.db"

    try:
        log("Decrypting the official JP CDB with Coneshell")
        decrypt_jp_cdb(official_asset, candidate_raw, args.coneshell)

        references: list[tuple[str, Path, int]] = []
        if external_stats is not None:
            references.append(("roboninon", external_database, 260))
        if output_db.exists():
            references.append(("jp-previous-readable", output_db, 130))

        log("Resolving JP names (roboninon first, previous JP database second)")
        mapping = resolve_mapping(
            target_db=candidate_raw,
            rainbow_paths=[],
            references=references,
            previous_db=usable_previous_raw,
            previous_mapping_path=previous_mapping_path,
            source_metadata=source_metadata,
        )
        rename = deobfuscate_database(candidate_raw, output_db, mapping)
        validate_database(output_db)
        os.replace(candidate_raw, raw_db)
        json_write(mapping_path, mapping)
        json_write(version_path, source_metadata)
        report = build_report(mapping, rename, region="JP")
        report_path.write_text(report, encoding="utf-8")
        log(report)
        return 0
    except Exception as official_error:
        candidate_raw.unlink(missing_ok=True)
        log(f"Official JP CDB recovery failed: {official_error}")

        if external_stats is not None:
            fallback_metadata = {
                **source_metadata,
                "source": "official-ios-cdn+roboninon-fallback",
            }
            temporary_output = output_db.with_suffix(output_db.suffix + ".tmp")
            shutil.copy2(external_database, temporary_output)
            os.replace(temporary_output, output_db)
            json_write(version_path, fallback_metadata)
            report = build_external_report(
                "JP", fallback_metadata, external_stats, args.external_url
            )
            report_path.write_text(report, encoding="utf-8")
            log(report)
            return 0

        if output_db.exists():
            log("Keeping the previous readable JP database")
            return 0
        raise RuntimeError(
            "no readable JP database is available; "
            f"roboninon error: {external_error}"
        ) from official_error


def update_cn_command(args: argparse.Namespace) -> int:
    output_dir = args.output_dir.resolve()
    cache_dir = args.cache_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    output_db = output_dir / "master_cn_unhash.db"
    mapping_path = cache_dir / "mapping_cn.json"
    version_path = output_dir / "version_cn.json"
    report_path = cache_dir / "REPORT_cn.md"
    current_version = json_load(version_path, {}) or {}
    current_mapping = json_load(mapping_path, {}) or {}
    rainbow_paths = args.rainbow or [Path("rainbow_cn.json")]
    resolved_rainbows = [path.resolve() for path in rainbow_paths]
    current_rainbows = rainbow_fingerprints(resolved_rainbows)

    build, version_sources, app_version = discover_cn_build(
        display_version=args.display_version
    )
    source_metadata = {
        "version": build["version"],
        "manifest_version": build["version"],
        "hash": build["md5"],
        "asset_md5": build["md5"],
        "storage_hash": build["storage_hash"],
        "platform": build["platform"],
        "cdn": build["cdn"],
        "app_version": app_version,
        "version_sources": version_sources,
    }
    if (
        not args.force
        and current_version.get("asset_md5") == build["md5"]
        and current_mapping.get("rainbows") == current_rainbows
        and output_db.exists()
    ):
        log(
            f"CN database is already current: {build['version']} "
            f"({build['platform']}, {build['md5']})"
        )
        return 0

    bundle_path = cache_dir / "master_cn_latest.unity3d"
    candidate_db = cache_dir / "master_cn_candidate.db"
    raw_db = cache_dir / "master_cn_latest.db"
    previous_raw_db = cache_dir / "master_cn_previous.db"
    storage_hash = build["storage_hash"]
    asset_url = (
        f"{build['cdn']}pool/AssetBundles/{build['platform']}/"
        f"{storage_hash[:2]}/{storage_hash}"
    )
    log(
        f"Downloading CN database {build['version']} "
        f"from {build['platform']} ({build['md5']})"
    )
    download(asset_url, bundle_path)
    actual_md5 = hashlib.md5(bundle_path.read_bytes()).hexdigest()
    if actual_md5 != build["md5"]:
        raise RuntimeError(
            f"CN bundle MD5 mismatch: expected {build['md5']}, got {actual_md5}"
        )
    if bundle_path.stat().st_size != int(build["size"]):
        raise RuntimeError(
            f"CN bundle size mismatch: expected {build['size']}, "
            f"got {bundle_path.stat().st_size}"
        )
    extract_unity_database(bundle_path, candidate_db)
    validate_database(candidate_db)
    if raw_db.exists():
        shutil.copy2(raw_db, previous_raw_db)
    os.replace(candidate_db, raw_db)

    references: list[tuple[str, Path, int]] = []
    # The committed readable output is a portable same-region previous version,
    # so cache eviction does not destroy the recovery chain.
    if output_db.exists():
        references.append(("cn-previous-readable", output_db, 130))
    for label, location, priority in args.reference or []:
        if location.startswith(("https://", "http://")):
            reference_path = cache_dir / "references" / f"{label}.db"
            if not reference_path.exists():
                download(location, reference_path, expected_sqlite=True)
        else:
            reference_path = Path(location).resolve()
        references.append((label, reference_path, priority))

    previous_mapping_path = mapping_path if mapping_path.exists() else None
    mapping = resolve_mapping(
        target_db=raw_db,
        rainbow_paths=resolved_rainbows,
        references=references,
        previous_db=previous_raw_db if previous_raw_db.exists() else None,
        previous_mapping_path=previous_mapping_path,
        source_metadata=source_metadata,
    )
    json_write(mapping_path, mapping)
    rename = deobfuscate_database(raw_db, output_db, mapping)
    json_write(version_path, source_metadata)
    report = build_report(mapping, rename, region="CN")
    report_path.write_text(report, encoding="utf-8")
    log(report)
    return 0


def deobfuscate_command(args: argparse.Namespace) -> int:
    references = [
        (label, Path(location).resolve(), priority)
        for label, location, priority in (args.reference or [])
    ]
    rainbow_paths = args.rainbow or [Path("rainbow_tw.json")]
    mapping = resolve_mapping(
        target_db=args.input.resolve(),
        rainbow_paths=[path.resolve() for path in rainbow_paths],
        references=references,
        previous_db=args.previous_db.resolve() if args.previous_db else None,
        previous_mapping_path=(
            args.previous_mapping.resolve() if args.previous_mapping else None
        ),
    )
    json_write(args.mapping.resolve(), mapping)
    rename = deobfuscate_database(
        args.input.resolve(), args.output.resolve(), mapping
    )
    log(build_report(mapping, rename))
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update", help="download and update automatically")
    update.add_argument("--output-dir", type=Path, default=Path("data"))
    update.add_argument("--cache-dir", type=Path, default=Path(".cache"))
    update.add_argument(
        "--rainbow",
        action="append",
        type=Path,
        default=None,
        help="rainbow JSON in priority order (repeatable)",
    )
    update.add_argument("--force", action="store_true")
    update.add_argument(
        "--reference",
        action="append",
        type=parse_reference,
        help="extra LABEL=PATH_OR_URL=PRIORITY reference (repeatable)",
    )
    update.set_defaults(function=update_command)

    update_jp = subparsers.add_parser(
        "update-jp", help="update JP from the official iOS CDB"
    )
    update_jp.add_argument("--output-dir", type=Path, default=Path("data"))
    update_jp.add_argument("--cache-dir", type=Path, default=Path(".cache"))
    update_jp.add_argument("--external-url", default=JP_EXTERNAL_URL)
    update_jp.add_argument("--coneshell", type=Path, default=JP_CONESHELL)
    update_jp.add_argument("--force", action="store_true")
    update_jp.set_defaults(function=update_jp_command)

    update_cn = subparsers.add_parser(
        "update-cn", help="update CN anonymously from official CDN manifests"
    )
    update_cn.add_argument("--output-dir", type=Path, default=Path("data"))
    update_cn.add_argument("--cache-dir", type=Path, default=Path(".cache"))
    update_cn.add_argument(
        "--rainbow",
        action="append",
        type=Path,
        default=None,
        help="CN rainbow JSON in priority order (repeatable)",
    )
    update_cn.add_argument(
        "--display-version",
        help="additional iOS manifest version candidate",
    )
    update_cn.add_argument("--force", action="store_true")
    update_cn.add_argument(
        "--reference",
        action="append",
        type=parse_reference,
        help="extra LABEL=PATH_OR_URL=PRIORITY CN reference (repeatable)",
    )
    update_cn.set_defaults(function=update_cn_command)

    deobfuscate = subparsers.add_parser(
        "deobfuscate", help="process a local SQLite database"
    )
    deobfuscate.add_argument("--input", type=Path, required=True)
    deobfuscate.add_argument("--output", type=Path, required=True)
    deobfuscate.add_argument("--mapping", type=Path, required=True)
    deobfuscate.add_argument(
        "--rainbow",
        action="append",
        type=Path,
        default=None,
        help="rainbow JSON in priority order (repeatable)",
    )
    deobfuscate.add_argument("--previous-db", type=Path)
    deobfuscate.add_argument("--previous-mapping", type=Path)
    deobfuscate.add_argument(
        "--reference",
        action="append",
        type=parse_reference,
        required=True,
        help="LABEL=LOCAL_PATH=PRIORITY reference (repeatable)",
    )
    deobfuscate.set_defaults(function=deobfuscate_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    return args.function(args)


if __name__ == "__main__":
    sys.exit(main())
