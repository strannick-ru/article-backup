import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

import requests

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

    def close(self):
        return None


class _FailingStreamResponse(_FakeResponse):
    def iter_content(self, chunk_size: int = 8192):
        yield self._body
        raise requests.exceptions.ChunkedEncodingError("stream interrupted")


class _HttpErrorResponse(_FakeResponse):
    def __init__(self, status_code: int):
        super().__init__("text/plain", b"")
        self.status_code = status_code

    def raise_for_status(self):
        response = requests.Response()
        response.status_code = self.status_code
        raise requests.HTTPError(f"{self.status_code} error", response=response)


class _DummyDB:
    pass


class _DummyDownloader(BaseDownloader):
    PLATFORM = "dummy"
    MAX_WORKERS = 2

    def _setup_session(self):
        # Tests patch session.get directly.
        return None

    def fetch_posts_list(
        self,
        existing_ids: set[str] | None = None,
        incremental: bool = False,
        safety_chunks: int = 1
    ):
        raise NotImplementedError

    def fetch_post(self, post_id: str):
        raise NotImplementedError

    def _parse_post(self, raw_data: dict):
        raise NotImplementedError

    def _to_markdown(self, post, asset_map):
        raise NotImplementedError


class _FailingWriteFile:
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __enter__(self):
        self._wrapped.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._wrapped.__exit__(exc_type, exc_val, exc_tb)

    def write(self, data: bytes):
        self._wrapped.write(b"partial")
        raise OSError("temporary disk write failure")


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

    def test_download_assets_uses_download_url_but_maps_original_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="boosty", author="author", download_assets=True)
            dl = _DummyDownloader(config, source, cast(Database, _DummyDB()))

            requested_urls = []

            def fake_get(url: str, stream: bool = True, timeout=None):
                requested_urls.append(url)
                return _FakeResponse("audio/mpeg", body=b"audio")

            dl.session.get = fake_get  # type: ignore[method-assign]

            asset_map = dl._download_assets(
                [
                    {
                        "url": "https://cdn.boosty.to/audio/audio-id",
                        "download_url": "https://cdn.boosty.to/audio/audio-id?sign=abc",
                        "alt": "audio.mp3",
                    }
                ],
                assets_dir,
            )

            self.assertEqual(requested_urls, ["https://cdn.boosty.to/audio/audio-id?sign=abc"])
            self.assertIn("https://cdn.boosty.to/audio/audio-id", asset_map)

    def test_download_assets_retries_network_errors_ten_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="boosty", author="author", download_assets=True)
            dl = _DummyDownloader(config, source, cast(Database, _DummyDB()))

            attempts = 0

            def fake_get(url: str, stream: bool = True, timeout=None):
                nonlocal attempts
                attempts += 1
                if attempts < 10:
                    raise requests.ConnectionError("temporary cdn failure")
                return _FakeResponse("audio/mpeg", body=b"audio")

            dl.session.get = fake_get  # type: ignore[method-assign]

            with patch("src.downloader.time.sleep") as sleep_mock:
                asset_map = dl._download_assets(
                    [{"url": "https://cdn.boosty.to/audio/audio-id", "alt": "audio.mp3"}],
                    assets_dir,
                )

            self.assertEqual(attempts, 10)
            self.assertEqual(
                [call.args[0] for call in sleep_mock.call_args_list],
                [3, 5, 7, 10, 15, 15, 15, 15, 15],
            )
            self.assertIn("https://cdn.boosty.to/audio/audio-id", asset_map)

    def test_download_assets_retries_stream_errors_and_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="boosty", author="author", download_assets=True)
            dl = _DummyDownloader(config, source, cast(Database, _DummyDB()))

            attempts = 0

            def fake_get(url: str, stream: bool = True, timeout=None):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    return _FailingStreamResponse("audio/mpeg", body=b"partial")
                return _FakeResponse("audio/mpeg", body=b"complete")

            dl.session.get = fake_get  # type: ignore[method-assign]

            with patch("src.downloader.time.sleep"):
                asset_map = dl._download_assets(
                    [{"url": "https://cdn.boosty.to/audio/audio-id", "alt": "audio.mp3"}],
                    assets_dir,
                )

            self.assertEqual(attempts, 2)
            filename = asset_map["https://cdn.boosty.to/audio/audio-id"]
            self.assertEqual((assets_dir / filename).read_bytes(), b"complete")
            self.assertFalse(any(path.read_bytes() == b"partial" for path in assets_dir.iterdir()))

    def test_download_assets_does_not_retry_permanent_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="boosty", author="author", download_assets=True)
            dl = _DummyDownloader(config, source, cast(Database, _DummyDB()))

            attempts = 0

            def fake_get(url: str, stream: bool = True, timeout=None):
                nonlocal attempts
                attempts += 1
                return _HttpErrorResponse(404)

            dl.session.get = fake_get  # type: ignore[method-assign]

            with patch("src.downloader.time.sleep"):
                asset_map = dl._download_assets(
                    [{"url": "https://cdn.boosty.to/audio/missing-id", "alt": "missing.mp3"}],
                    assets_dir,
                )

            self.assertEqual(attempts, 1)
            self.assertEqual(asset_map, {})

    def test_download_assets_retries_write_errors_and_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="boosty", author="author", download_assets=True)
            dl = _DummyDownloader(config, source, cast(Database, _DummyDB()))

            def fake_get(url: str, stream: bool = True, timeout=None):
                return _FakeResponse("audio/mpeg", body=b"complete")

            dl.session.get = fake_get  # type: ignore[method-assign]

            real_open = open
            open_attempts = 0

            def flaky_open(path, mode="r", *args, **kwargs):
                nonlocal open_attempts
                if "wb" in mode:
                    open_attempts += 1
                    wrapped = real_open(path, mode, *args, **kwargs)
                    if open_attempts == 1:
                        return _FailingWriteFile(wrapped)
                    return wrapped
                return real_open(path, mode, *args, **kwargs)

            with patch("src.downloader.time.sleep"), patch("builtins.open", flaky_open):
                asset_map = dl._download_assets(
                    [{"url": "https://cdn.boosty.to/audio/audio-id", "alt": "audio.mp3"}],
                    assets_dir,
                )

            self.assertEqual(open_attempts, 2)
            filename = asset_map["https://cdn.boosty.to/audio/audio-id"]
            self.assertEqual((assets_dir / filename).read_bytes(), b"complete")
            self.assertFalse(any(path.read_bytes() == b"partial" for path in assets_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
