import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "priconne_unhash.py"
SPEC = importlib.util.spec_from_file_location("priconne_unhash", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_database(path: Path, table_name: str, column_names: tuple[str, str]) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            f'CREATE TABLE "{table_name}" ('
            f'"{column_names[0]}" INTEGER PRIMARY KEY, '
            f'"{column_names[1]}" TEXT NOT NULL)'
        )
        db.executemany(
            f'INSERT INTO "{table_name}" VALUES (?, ?)',
            [(1, "one"), (2, "two"), (3, "three")],
        )
        db.commit()


class UnhashTests(unittest.TestCase):
    def test_cn_headers_and_discovery_are_ios_only(self):
        headers = MODULE.cn_request_headers("11.7.2")
        self.assertEqual(headers["PLATFORM"], "1")
        self.assertEqual(headers["PLATFORM-ID"], "1")
        self.assertEqual(headers["DEVICE"], "1")

        observed = []

        def probe(version, resources, platforms=("iOS",)):
            observed.append((version, tuple(resources), platforms))
            if version != MODULE.CN_IOS_BASELINE_VERSION:
                return None
            return {
                "version": version,
                "platform": "iOS",
                "cdn": "https://ios.example/",
                "path": "a/masterdata_master.unity3d",
                "md5": "a" * 32,
                "storage_hash": "b" * 16,
                "size": 123,
            }

        with (
            patch.object(MODULE, "fetch_cn_app_version", return_value="11.7.2"),
            patch.object(
                MODULE,
                "fetch_cn_status",
                return_value=(
                    {"manifest_ver": "202607312055", "resource": ["ios.example/"]},
                    "11.7.2",
                ),
            ),
            patch.object(MODULE, "probe_cn_build", side_effect=probe),
        ):
            build, sources, _ = MODULE.discover_cn_build()

        self.assertEqual(build["version"], MODULE.CN_IOS_BASELINE_VERSION)
        self.assertEqual(set(sources), {"official-ios", "ios-baseline"})
        self.assertTrue(observed)
        self.assertTrue(all(platforms == ("iOS",) for _, _, platforms in observed))

    def test_cn_manifest_uses_storage_hash_when_present(self):
        current = MODULE.parse_cn_asset_line(
            "a/masterdata_master.unity3d,"
            "92f78a332512683593ef24406ad428db,"
            "3f33b27b9f8294ee,tutorial2,13292264,"
        )
        self.assertEqual(current["md5"], "92f78a332512683593ef24406ad428db")
        self.assertEqual(current["storage_hash"], "3f33b27b9f8294ee")
        self.assertEqual(current["size"], 13292264)

        legacy = MODULE.parse_cn_asset_line(
            "a/masterdata_master.unity3d,"
            "92f78a332512683593ef24406ad428db,tutorial2,13292264,"
        )
        self.assertEqual(legacy["storage_hash"], legacy["md5"])

    def test_reference_names_are_transferred_and_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.db"
            target = root / "target.db"
            output = root / "output.db"
            rainbow = root / "rainbow.json"
            make_database(reference, "unit_data", ("unit_id", "name"))
            make_database(target, "v1_" + "a" * 64, ("b" * 64, "c" * 64))
            rainbow.write_text("{}", encoding="utf-8")

            mapping = MODULE.resolve_mapping(
                target,
                rainbow,
                [("test", reference, 100)],
            )
            self.assertEqual(mapping["summary"]["tables_mapped"], 1)
            self.assertEqual(mapping["summary"]["columns_mapped"], 2)

            result = MODULE.deobfuscate_database(target, output, mapping)
            self.assertEqual(result["integrity_check"], "ok")
            with closing(sqlite3.connect(output)) as db:
                columns = [row[1] for row in db.execute('PRAGMA table_info("unit_data")')]
                self.assertEqual(columns, ["unit_id", "name"])

    def test_rainbow_direct_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table_hash = "v1_" + "d" * 64
            column_hash = "e" * 64
            target = root / "target.db"
            output = root / "output.db"
            mapping_path = root / "rainbow.json"
            with closing(sqlite3.connect(target)) as db:
                db.execute(
                    f'CREATE TABLE "{table_hash}" ("{column_hash}" INTEGER PRIMARY KEY)'
                )
                db.commit()
            mapping_path.write_text(
                json.dumps(
                    {
                        table_hash: {
                            column_hash: "unit_id",
                            "--table_name": "unit_data",
                        }
                    }
                ),
                encoding="utf-8",
            )
            mapping = MODULE.resolve_mapping(target, mapping_path, [])
            MODULE.deobfuscate_database(target, output, mapping)
            with closing(sqlite3.connect(output)) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0],
                    "unit_data",
                )

    def test_first_rainbow_file_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table_hash = "v1_" + "7" * 64
            column_hash = "8" * 64
            target = root / "target.db"
            primary = root / "rainbow_tw.json"
            fallback = root / "rainbow_old.json"
            with closing(sqlite3.connect(target)) as db:
                db.execute(
                    f'CREATE TABLE "{table_hash}" ("{column_hash}" INTEGER)'
                )
                db.commit()
            primary.write_text(
                json.dumps(
                    {
                        table_hash: {
                            column_hash: "primary_id",
                            "--table_name": "primary_table",
                        }
                    }
                ),
                encoding="utf-8",
            )
            fallback.write_text(
                json.dumps(
                    {
                        table_hash: {
                            column_hash: "fallback_id",
                            "--table_name": "fallback_table",
                        }
                    }
                ),
                encoding="utf-8",
            )

            mapping = MODULE.resolve_mapping(target, [primary, fallback], [])
            resolved = mapping["tables"][table_hash]
            self.assertEqual(resolved["name"], "primary_table")
            self.assertEqual(resolved["columns"][column_hash], "primary_id")

    def test_previous_snapshot_migrates_names_to_new_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_table = "v1_" + "1" * 64
            new_table = "v1_" + "2" * 64
            old_columns = ("3" * 64, "4" * 64)
            new_columns = ("5" * 64, "6" * 64)
            previous = root / "previous.db"
            target = root / "target.db"
            rainbow = root / "rainbow.json"
            previous_mapping = root / "previous_mapping.json"
            make_database(previous, old_table, old_columns)
            make_database(target, new_table, new_columns)
            rainbow.write_text("{}", encoding="utf-8")
            previous_mapping.write_text(
                json.dumps(
                    {
                        "tables": {
                            old_table: {
                                "name": "unit_data",
                                "columns": {
                                    old_columns[0]: "unit_id",
                                    old_columns[1]: "name",
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            mapping = MODULE.resolve_mapping(
                target,
                rainbow,
                [],
                previous_db=previous,
                previous_mapping_path=previous_mapping,
            )
            migrated = mapping["tables"][new_table]
            self.assertEqual(migrated["name"], "unit_data")
            self.assertEqual(migrated["columns"][new_columns[0]], "unit_id")
            self.assertEqual(migrated["columns"][new_columns[1]], "name")


if __name__ == "__main__":
    unittest.main()
