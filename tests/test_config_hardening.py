import os
import tempfile
import unittest
from pathlib import Path

from backup import generate_hugo_config
from src.config import Auth, Config, HugoConfig, load_config


class ConfigHardeningTests(unittest.TestCase):
    def test_load_config_accepts_empty_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.yaml"
            cfg_path.write_text("", encoding="utf-8")

            cfg = load_config(cfg_path)

            self.assertEqual(cfg.output_dir, Path("./backup"))
            self.assertEqual(cfg.sources, [])

    def test_generate_hugo_config_escapes_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = Path.cwd()
            tmp_path = Path(tmp)
            (tmp_path / "site").mkdir(parents=True, exist_ok=True)

            try:
                os.chdir(tmp_path)
                cfg = Config(
                    output_dir=tmp_path / "backup",
                    auth=Auth(),
                    hugo=HugoConfig(
                        base_url='https://example.com/a"b',
                        title='Bob\'s "backup"',
                        language_code="ru",
                        default_theme='light"mode',
                    ),
                )

                generate_hugo_config(cfg)
                toml = (tmp_path / "site" / "hugo.toml").read_text(encoding="utf-8")

                self.assertIn('title = "Bob\'s \\"backup\\""', toml)
                self.assertIn('baseURL = "https://example.com/a\\"b"', toml)
                self.assertIn('default_theme = "light\\"mode"', toml)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
