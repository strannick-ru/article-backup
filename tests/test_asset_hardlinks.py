import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "site" / "deduplicate-assets.sh"


class AssetHardlinkTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "backup"
        self.public = self.root / "public"

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_pair(self, source_data=b"content", public_data=None):
        relative = Path("boosty/author/posts/post/assets/file.mp4")
        source_file = self.source / relative
        public_file = self.public / relative
        source_file.parent.mkdir(parents=True, exist_ok=True)
        public_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_bytes(source_data)
        public_file.write_bytes(source_data if public_data is None else public_data)
        return source_file, public_file

    def run_script(self, env=None):
        return subprocess.run(
            ["bash", str(SCRIPT), str(self.source), str(self.public)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_identical_asset_is_replaced_with_hardlink(self):
        source_file, public_file = self.make_pair()

        result = self.run_script()

        self.assertEqual(source_file.stat().st_ino, public_file.stat().st_ino)
        self.assertEqual(source_file.read_bytes(), b"content")
        self.assertIn("Связано файлов: 1", result.stdout)
        self.assertIn("Сэкономлено байт: 7", result.stdout)

    def test_different_public_file_is_preserved(self):
        source_file, public_file = self.make_pair(public_data=b"transformed")
        old_inode = public_file.stat().st_ino

        result = self.run_script()

        self.assertEqual(public_file.stat().st_ino, old_inode)
        self.assertNotEqual(source_file.stat().st_ino, public_file.stat().st_ino)
        self.assertEqual(public_file.read_bytes(), b"transformed")
        self.assertIn("Пропущено файлов: 1", result.stdout)

    def test_link_failure_keeps_public_copy(self):
        source_file, public_file = self.make_pair()
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_ln = fake_bin / "ln"
        fake_ln.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_ln.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"

        result = self.run_script(env)

        self.assertNotEqual(source_file.stat().st_ino, public_file.stat().st_ino)
        self.assertEqual(public_file.read_bytes(), b"content")
        self.assertIn("Пропущено файлов: 1", result.stdout)

    def test_symlinked_public_parent_outside_root_is_not_modified(self):
        relative = Path("boosty/author/posts/post/assets/file.mp4")
        source_file = self.source / relative
        source_file.parent.mkdir(parents=True)
        source_file.write_bytes(b"source")

        outside = self.root / "outside"
        outside_target = outside / "author/posts/post/assets/file.mp4"
        outside_target.parent.mkdir(parents=True)
        outside_target.write_bytes(b"source")
        self.public.mkdir()
        (self.public / "boosty").symlink_to(outside, target_is_directory=True)

        self.run_script()

        self.assertEqual(outside_target.read_bytes(), b"source")
        self.assertNotEqual(source_file.stat().st_ino, outside_target.stat().st_ino)


class LocalBuildHardlinkTests(unittest.TestCase):
    def test_build_cleans_public_before_hugo_and_deduplicates_afterwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            site.mkdir()
            (site / "build.sh").write_bytes((ROOT / "site/build.sh").read_bytes())
            (site / "deduplicate-assets.sh").write_bytes(SCRIPT.read_bytes())
            (site / "build.sh").chmod(0o755)
            (site / "deduplicate-assets.sh").chmod(0o755)

            relative = Path("boosty/author/posts/post/assets/file.mp4")
            source_file = site / "content" / relative
            source_file.parent.mkdir(parents=True)
            source_file.write_bytes(b"video")
            stale = site / "public/stale.txt"
            stale.parent.mkdir()
            stale.write_text("stale", encoding="utf-8")

            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_hugo = fake_bin / "hugo"
            fake_hugo.write_text(
                "#!/bin/bash\n"
                "[ ! -e public/stale.txt ] || exit 42\n"
                "mkdir -p public/boosty/author/posts/post/assets public/css\n"
                "cp content/boosty/author/posts/post/assets/file.mp4 "
                "public/boosty/author/posts/post/assets/file.mp4\n",
                encoding="utf-8",
            )
            fake_hugo.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"

            public_file = site / "public" / relative
            for _ in range(2):
                subprocess.run(["bash", str(site / "build.sh")], check=True, env=env)
                self.assertFalse(stale.exists())
                self.assertEqual(source_file.stat().st_ino, public_file.stat().st_ino)
                self.assertEqual(source_file.read_bytes(), b"video")


class DockerBuildHardlinkTests(unittest.TestCase):
    def test_compose_hugo_commands_clean_public_and_stop_on_failure(self):
        for filename in ("docker-compose.yml", "docker-compose-dev.yml"):
            compose = yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))
            command = compose["services"]["hugo"]["command"][0]
            self.assertIn("set -e", command, filename)
            self.assertIn("rm -rf public", command, filename)
            self.assertLess(command.index("rm -rf public"), command.index("hugo --minify"))

    def test_run_docker_hugo_deduplicates_on_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "site").mkdir()
            (root / "run-docker.sh").write_bytes((ROOT / "run-docker.sh").read_bytes())
            (root / "site/deduplicate-assets.sh").write_bytes(SCRIPT.read_bytes())
            (root / "run-docker.sh").chmod(0o755)
            (root / "site/deduplicate-assets.sh").chmod(0o755)

            relative = Path("boosty/author/posts/post/assets/file.mp4")
            source_file = root / "backup" / relative
            public_file = root / "site/public" / relative
            source_file.parent.mkdir(parents=True)
            public_file.parent.mkdir(parents=True)
            source_file.write_bytes(b"video")
            public_file.write_bytes(b"video")

            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_docker.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"

            subprocess.run(
                ["bash", "run-docker.sh", "hugo"],
                cwd=root,
                check=True,
                env=env,
            )

            self.assertEqual(source_file.stat().st_ino, public_file.stat().st_ino)


if __name__ == "__main__":
    unittest.main()
