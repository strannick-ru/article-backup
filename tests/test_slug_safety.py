import tempfile
import unittest
from pathlib import Path

from src.config import Auth, Config, Source
from src.database import Database, PostRecord
from src.downloader import BaseDownloader, Post


class _SlugDummyDownloader(BaseDownloader):
    PLATFORM = "dummy"

    def _setup_session(self):
        return None

    def fetch_posts_list(self, existing_ids=None, incremental=False, safety_chunks=1):
        raise NotImplementedError

    def fetch_post(self, post_id: str):
        raise NotImplementedError

    def _parse_post(self, raw_data: dict):
        raise NotImplementedError

    def _to_markdown(self, post: Post, asset_map: dict[str, str]) -> str:
        return "content\n"


class SlugSafetyTests(unittest.TestCase):
    def test_slug_unique_for_same_title_and_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="sponsr", author="author")

            with Database(tmp_path / "test.db") as db:
                dl = _SlugDummyDownloader(config, source, db)

                post1 = Post(
                    post_id="101",
                    title="Одинаковый заголовок",
                    content_html="",
                    post_date="2025-01-01T00:00:00",
                    source_url="https://example.com/101",
                    tags=[],
                    assets=[],
                )
                post2 = Post(
                    post_id="202",
                    title="Одинаковый заголовок",
                    content_html="",
                    post_date="2025-01-01T01:00:00",
                    source_url="https://example.com/202",
                    tags=[],
                    assets=[],
                )

                dl._save_post(post1)
                dl._save_post(post2)

                rec1 = db.get_post("dummy", "author", "101")
                rec2 = db.get_post("dummy", "author", "202")
                self.assertIsNotNone(rec1)
                self.assertIsNotNone(rec2)
                self.assertNotEqual(rec1.slug, rec2.slug)
                self.assertTrue((Path(rec1.local_path) / "index.md").exists())
                self.assertTrue((Path(rec2.local_path) / "index.md").exists())

    def test_existing_slug_is_reused_for_same_post_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform="sponsr", author="author")

            with Database(tmp_path / "test.db") as db:
                old_slug = "2025-01-01-old-style-slug"
                old_path = str(tmp_path / "dummy" / "author" / "posts" / old_slug)
                db.add_post(PostRecord(
                    platform="dummy",
                    author="author",
                    post_id="legacy-id",
                    title="Old",
                    slug=old_slug,
                    post_date="2025-01-01T00:00:00",
                    source_url="https://example.com/legacy",
                    local_path=old_path,
                    tags="[]",
                    synced_at="2025-01-01T00:00:00+00:00",
                ))

                dl = _SlugDummyDownloader(config, source, db)
                updated = Post(
                    post_id="legacy-id",
                    title="Новое имя",
                    content_html="",
                    post_date="2025-01-01T02:00:00",
                    source_url="https://example.com/legacy",
                    tags=[],
                    assets=[],
                )

                dl._save_post(updated)

                rec = db.get_post("dummy", "author", "legacy-id")
                self.assertIsNotNone(rec)
                self.assertEqual(rec.slug, old_slug)
                self.assertTrue((Path(rec.local_path) / "index.md").exists())


if __name__ == "__main__":
    unittest.main()
