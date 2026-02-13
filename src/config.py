# src/config.py
"""Загрузка и валидация конфигурации."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
import os

Platform = Literal['sponsr', 'boosty']


@dataclass
class Source:
    platform: Platform
    author: str
    download_assets: bool = True
    display_name: str | None = None
    asset_types: list[str] | None = None

@dataclass
class Auth:
    sponsr_cookie_file: Path | None = None
    boosty_cookie_file: Path | None = None
    boosty_auth_file: Path | None = None  # Authorization: Bearer ...


@dataclass
class HugoConfig:
    base_url: str = "http://localhost:1313/"
    title: str = "Бэкап статей"
    language_code: str = "ru"
    default_theme: str = "light"


@dataclass
class Config:
    output_dir: Path
    auth: Auth
    sources: list[Source] = field(default_factory=list)
    hugo: HugoConfig = field(default_factory=HugoConfig)


def load_config(config_path: Path) -> Config:
    """Загружает конфигурацию из YAML-файла."""
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("Корень config.yaml должен быть объектом (mapping)")

    # output_dir
    env_output_dir = os.environ.get('BACKUP_OUTPUT_DIR')
    if env_output_dir:
        output_dir = Path(env_output_dir)
    else:
        output_dir = Path(data.get('output_dir', './backup'))

    # auth
    auth_data = data.get('auth', {})
    if auth_data is None:
        auth_data = {}
    if not isinstance(auth_data, dict):
        raise ValueError("Секция 'auth' должна быть объектом")
    auth = Auth(
        sponsr_cookie_file=_to_path(auth_data.get('sponsr_cookie_file')),
        boosty_cookie_file=_to_path(auth_data.get('boosty_cookie_file')),
        boosty_auth_file=_to_path(auth_data.get('boosty_auth_file')),
    )

    # sources
    sources = []
    sources_data = data.get('sources', [])
    if sources_data is None:
        sources_data = []
    if not isinstance(sources_data, list):
        raise ValueError("Секция 'sources' должна быть списком")

    for src in sources_data:
        if not isinstance(src, dict):
            raise ValueError("Каждый элемент в 'sources' должен быть объектом")
        if 'platform' not in src or 'author' not in src:
            raise ValueError("Каждый источник в 'sources' должен содержать 'platform' и 'author'")
        sources.append(Source(
            platform=src['platform'],
            author=src['author'],
            download_assets=src.get('download_assets', True),
            display_name=src.get('display_name'),
            asset_types=src.get('asset_types'),
        ))

    # hugo
    hugo_data = data.get('hugo', {})
    if hugo_data is None:
        hugo_data = {}
    if not isinstance(hugo_data, dict):
        raise ValueError("Секция 'hugo' должна быть объектом")
    hugo = HugoConfig(
        base_url=hugo_data.get('base_url', HugoConfig.base_url),
        title=hugo_data.get('title', HugoConfig.title),
        language_code=hugo_data.get('language_code', HugoConfig.language_code),
        default_theme=hugo_data.get('default_theme', HugoConfig.default_theme),
    )

    return Config(output_dir=output_dir, auth=auth, sources=sources, hugo=hugo)


def _to_path(value: str | None) -> Path | None:
    """Конвертирует строку в Path или возвращает None."""
    return Path(value) if value else None


def load_cookie(cookie_file: Path | None) -> str:
    """Загружает cookie из файла."""
    if cookie_file is None:
        raise FileNotFoundError("Cookie file path not specified")
    if not cookie_file.exists():
        raise FileNotFoundError(f"Cookie file not found: {cookie_file}")
    return cookie_file.read_text(encoding='utf-8').strip()


def load_auth_header(auth_file: Path | None) -> str:
    """Загружает Authorization header из файла."""
    if auth_file is None:
        raise FileNotFoundError("Auth file path not specified")
    if not auth_file.exists():
        raise FileNotFoundError(f"Auth file not found: {auth_file}")
    return auth_file.read_text(encoding='utf-8').strip()
