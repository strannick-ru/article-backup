"""Docker-сборка Hugo требует, чтобы site/content был реальным каталогом.

Hugo не заходит в content, если это симлинк за пределы корня проекта, и молча
собирает пустой сайт. Docker резолвит цель bind-mount через такой симлинк и
монтирует бэкап мимо /site/content.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerContentMountpointTests(unittest.TestCase):
    def run_script(self, root: Path, *args: str) -> None:
        fake_bin = root / "bin"
        fake_bin.mkdir()
        fake_docker = fake_bin / "docker"
        fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_docker.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"

        subprocess.run(
            ["bash", "run-docker.sh", *args],
            cwd=root,
            check=True,
            env=env,
        )

    def make_root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "site").mkdir()
        (root / "backup").mkdir()
        (root / "run-docker.sh").write_bytes((ROOT / "run-docker.sh").read_bytes())
        (root / "run-docker.sh").chmod(0o755)
        (root / "site/deduplicate-assets.sh").write_bytes(
            (ROOT / "site" / "deduplicate-assets.sh").read_bytes()
        )
        (root / "site/deduplicate-assets.sh").chmod(0o755)
        return root

    def test_existing_symlink_is_replaced_with_real_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            (root / "site/content").symlink_to("../backup")

            self.run_script(root, "hugo")

            content = root / "site/content"
            self.assertFalse(content.is_symlink(), "site/content остался симлинком")
            self.assertTrue(content.is_dir(), "site/content не является каталогом")

    def test_missing_content_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)

            self.run_script(root, "hugo")

            content = root / "site/content"
            self.assertFalse(content.is_symlink())
            self.assertTrue(content.is_dir())

    def test_populated_content_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            content = root / "site/content"
            content.mkdir()
            (content / "keep.md").write_text("данные", encoding="utf-8")

            self.run_script(root, "hugo")

            self.assertFalse(content.is_symlink())
            self.assertEqual((content / "keep.md").read_text(encoding="utf-8"), "данные")


if __name__ == "__main__":
    unittest.main()
