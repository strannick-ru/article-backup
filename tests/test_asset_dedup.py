import tempfile
import unittest
from pathlib import Path
from typing import cast

from src.config import Auth, Config, Source
from src.database import Database
from src.downloader import BaseDownloader


class _FakeResponse:
    def __init__(self, content_type: str, body: bytes):
        self.headers = {"Content-Type": content_type}
        self._body = body

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size: int = 8192):
        # Yield at least one chunk to trigger file write.
        yield self._body


class _DummyDB:
    pass


class _DummyDownloader(BaseDownloader):
    PLATFORM = "dummy"
    MAX_WORKERS = 2

    def _setup_session(self):
        # Tests patch session.get directly.
        return None

    def fetch_posts_list(self):
        raise NotImplementedError

    def fetch_post(self, post_id: str):
        raise NotImplementedError

    def _parse_post(self, raw_data: dict):
        raise NotImplementedError

    def _to_markdown(self, post, asset_map):
        raise NotImplementedError


class AssetDedupTests(unittest.TestCase):
    def test_download_assets_deduplicates_colliding_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="sponsr", author="author", download_assets=True)
            dl = _DummyDownloader(config, source, cast(Database, _DummyDB()))

            def fake_get(url: str, stream: bool = True, timeout=None):
                # URLs intentionally do not contain extensions.
                return _FakeResponse("image/jpeg", body=(url + "\n").encode("ascii"))

            dl.session.get = fake_get  # type: ignore[method-assign]

            assets = [
                {"url": "https://example.test/media/1", "alt": "same name"},
                {"url": "https://example.test/media/2", "alt": "same name"},
            ]

            asset_map = dl._download_assets(assets, assets_dir)

            self.assertEqual(set(asset_map.keys()), {a["url"] for a in assets})

            filenames = list(asset_map.values())
            self.assertEqual(len(filenames), 2)
            self.assertNotEqual(filenames[0], filenames[1])

            for fn in filenames:
                self.assertTrue((assets_dir / fn).exists(), msg=f"missing file: {fn}")

    def test_download_assets_deduplicates_when_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="sponsr", author="author", download_assets=True)
            dl = _DummyDownloader(config, source, cast(Database, _DummyDB()))

            # Pre-create a file with the expected base name.
            base = dl._make_asset_filename(
                "https://example.test/media/1",
                "image/jpeg",
                "same name",
            )
            (assets_dir / base).write_bytes(b"existing")

            def fake_get(url: str, stream: bool = True, timeout=None):
                return _FakeResponse("image/jpeg", body=b"downloaded")

            dl.session.get = fake_get  # type: ignore[method-assign]

            assets = [{"url": "https://example.test/media/1", "alt": "same name"}]
            asset_map = dl._download_assets(assets, assets_dir)

            self.assertIn("https://example.test/media/1", asset_map)
            self.assertNotEqual(asset_map["https://example.test/media/1"], base)
            self.assertTrue((assets_dir / asset_map["https://example.test/media/1"]).exists())

    def test_download_assets_keeps_unique_names_under_parallelism(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="sponsr", author="author", download_assets=True)
            dl = _DummyDownloader(config, source, cast(Database, _DummyDB()))
            dl.MAX_WORKERS = 5

            def fake_get(url: str, stream: bool = True, timeout=None):
                return _FakeResponse("image/jpeg", body=(url + "\n").encode("ascii"))

            dl.session.get = fake_get  # type: ignore[method-assign]

            assets = [
                {"url": f"https://example.test/media/{i}", "alt": "same name"}
                for i in range(20)
            ]

            asset_map = dl._download_assets(assets, assets_dir)

            self.assertEqual(len(asset_map), 20)
            filenames = list(asset_map.values())
            self.assertEqual(len(set(filenames)), 20)
            for fn in filenames:
                self.assertTrue((assets_dir / fn).exists(), msg=f"missing file: {fn}")


if __name__ == "__main__":
    unittest.main()
