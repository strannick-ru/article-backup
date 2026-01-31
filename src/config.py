# src/config.py
"""Загрузка и валидация конфигурации."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

Platform = Literal['sponsr', 'boosty']


@dataclass
class Source:
    platform: Platform
    author: str
    download_assets: bool = True
    display_name: str | None = None

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

    # output_dir
    output_dir = Path(data.get('output_dir', './backup'))

    # auth
    auth_data = data.get('auth', {})
    auth = Auth(
        sponsr_cookie_file=_to_path(auth_data.get('sponsr_cookie_file')),
        boosty_cookie_file=_to_path(auth_data.get('boosty_cookie_file')),
        boosty_auth_file=_to_path(auth_data.get('boosty_auth_file')),
    )

    # sources
    sources = []
    for src in data.get('sources', []):
        sources.append(Source(
            platform=src['platform'],
            author=src['author'],
            download_assets=src.get('download_assets', True),
            display_name=src.get('display_name'),
        ))

    # hugo
    hugo_data = data.get('hugo', {})
    hugo = HugoConfig(
        base_url=hugo_data.get('base_url', HugoConfig.base_url),
        title=hugo_data.get('title', HugoConfig.title),
        language_code=hugo_data.get('language_code', HugoConfig.language_code),
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