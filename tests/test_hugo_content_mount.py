"""Hugo читает бэкап через module.mounts, а не через симлинк site/content.

Симлинк за пределы корня проекта Hugo молча игнорирует, собирая сайт без статей.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backup import generate_hugo_config
from src.config import Auth, Config, HugoConfig


class HugoContentMountTests(unittest.TestCase):
    def generate(self, output_dir_name: str, docker: bool) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            (tmp_path / "site").mkdir()
            output_dir = tmp_path / output_dir_name
            output_dir.mkdir(parents=True)

            old_cwd = Path.cwd()
            old_env = os.environ.get("BACKUP_OUTPUT_DIR")
            try:
                os.chdir(tmp_path)
                if docker:
                    os.environ["BACKUP_OUTPUT_DIR"] = "/app/backup"
                else:
                    os.environ.pop("BACKUP_OUTPUT_DIR", None)

                generate_hugo_config(
                    Config(
                        output_dir=output_dir,
                        auth=Auth(),
                        hugo=HugoConfig(),
                    )
                )
                return (tmp_path / "site" / "hugo.toml").read_text(encoding="utf-8")
            finally:
                os.chdir(old_cwd)
                if old_env is None:
                    os.environ.pop("BACKUP_OUTPUT_DIR", None)
                else:
                    os.environ["BACKUP_OUTPUT_DIR"] = old_env

    def test_local_config_mounts_output_dir_as_content(self):
        toml = self.generate("backup", docker=False)

        self.assertIn("[[module.mounts]]", toml)
        self.assertIn('source = "../backup"', toml)
        self.assertIn('target = "content"', toml)

    def test_mount_path_follows_custom_output_dir(self):
        toml = self.generate("data/articles", docker=False)

        self.assertIn('source = "../data/articles"', toml)

    def test_docker_config_has_no_mount(self):
        # В контейнере бэкап монтируется прямо в /site/content.
        toml = self.generate("backup", docker=True)

        self.assertNotIn("module.mounts", toml)


if __name__ == "__main__":
    unittest.main()
