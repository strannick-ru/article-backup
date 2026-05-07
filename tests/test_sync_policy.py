import unittest
import sys
import tempfile
from pathlib import Path

import backup
from src.config import Auth, Config, Source, SyncConfig


class DummyDownloader:
    checks: list[str] = []
    synced: list[str] = []
    check_failures: dict[str, Exception] = {}
    sync_failures: dict[str, Exception] = {}

    def __init__(self, config, source, db):
        self.source = source

    def check_auth(self):
        DummyDownloader.checks.append(self.source.author)
        error = DummyDownloader.check_failures.get(self.source.author)
        if error:
            raise error

    def sync(self):
        DummyDownloader.synced.append(self.source.author)
        error = DummyDownloader.sync_failures.get(self.source.author)
        if error:
            raise error


class SyncPolicyTests(unittest.TestCase):
    def setUp(self):
        self.old_get_downloader = backup.get_downloader
        backup.get_downloader = lambda platform, config, source, db: DummyDownloader(config, source, db)
        DummyDownloader.checks = []
        DummyDownloader.synced = []
        DummyDownloader.check_failures = {}
        DummyDownloader.sync_failures = {}

    def tearDown(self):
        backup.get_downloader = self.old_get_downloader

    def make_config(self, on_error):
        return Config(
            output_dir=Path("/tmp/test"),
            auth=Auth(),
            sources=[
                Source(platform="sponsr", author="good"),
                Source(platform="boosty", author="bad"),
            ],
            sync=SyncConfig(on_error=on_error),
        )

    def test_preflight_continue_filters_failed_sources(self):
        config = self.make_config("continue")
        DummyDownloader.check_failures = {"bad": RuntimeError("401 Unauthorized")}

        ready_sources, errors = backup.preflight_sources(config, object())

        self.assertEqual([source.author for source in ready_sources], ["good"])
        self.assertEqual([source.author for source, _ in errors], ["bad"])
        self.assertEqual(DummyDownloader.checks, ["good", "bad"])

    def test_sync_all_continue_keeps_syncing_after_source_error(self):
        config = self.make_config("continue")
        DummyDownloader.sync_failures = {"good": RuntimeError("boom")}

        errors = backup.sync_all(config, object())

        self.assertEqual([source.author for source, _ in errors], ["good"])
        self.assertEqual(DummyDownloader.synced, ["good", "bad"])

    def test_sync_all_stop_stops_after_first_source_error(self):
        config = self.make_config("stop")
        DummyDownloader.sync_failures = {"good": RuntimeError("boom")}

        errors = backup.sync_all(config, object())

        self.assertEqual([source.author for source, _ in errors], ["good"])
        self.assertEqual(DummyDownloader.synced, ["good"])

    def test_main_continue_preflight_errors_do_not_exit_with_failure(self):
        config = self.make_config("continue")
        DummyDownloader.check_failures = {"bad": RuntimeError("401 Unauthorized")}

        class DummyDatabase:
            def __init__(self, path):
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        old_argv = sys.argv
        old_load_config = backup.load_config
        old_database = backup.Database
        old_ensure_link = backup.ensure_site_content_link
        old_generate_hugo_config = backup.generate_hugo_config

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.yaml"
            cfg_path.write_text("", encoding="utf-8")
            config.output_dir = Path(tmp) / "backup"

            try:
                sys.argv = ["backup.py", "--config", str(cfg_path)]
                backup.load_config = lambda path: config
                backup.Database = DummyDatabase
                backup.ensure_site_content_link = lambda cfg: None
                backup.generate_hugo_config = lambda cfg: None

                backup.main()
            except SystemExit as e:
                self.fail(f"main() exited with {e.code} for continue policy")
            finally:
                sys.argv = old_argv
                backup.load_config = old_load_config
                backup.Database = old_database
                backup.ensure_site_content_link = old_ensure_link
                backup.generate_hugo_config = old_generate_hugo_config

        self.assertEqual(DummyDownloader.synced, ["good"])


if __name__ == "__main__":
    unittest.main()
