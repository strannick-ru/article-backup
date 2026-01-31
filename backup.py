#!/usr/bin/env python3
# backup.py
"""CLI точка входа для бэкапа статей."""

import argparse
import sys
from pathlib import Path

from src.config import Config, load_config, Source
from src.database import Database
from src.utils import is_post_url, parse_post_url
from src.sponsr import SponsorDownloader
from src.boosty import BoostyDownloader


def get_downloader(platform: str, config: Config, source: Source, db: Database):
    """Возвращает загрузчик для платформы."""
    if platform == 'sponsr':
        return SponsorDownloader(config, source, db)
    elif platform == 'boosty':
        return BoostyDownloader(config, source, db)
    else:
        raise ValueError(f"Неизвестная платформа: {platform}")


def sync_all(config: Config, db: Database):
    """Синхронизирует всех авторов из конфига."""
    for source in config.sources:
        try:
            downloader = get_downloader(source.platform, config, source, db)
            downloader.sync()
        except Exception as e:
            print(f"[{source.platform}] Ошибка при синхронизации {source.author}: {e}")


def download_single_post(url: str, config: Config, db: Database):
    """Скачивает один пост по URL."""
    platform, author, post_id = parse_post_url(url)

    # Создаём Source для этого автора
    source = Source(platform=platform, author=author, download_assets=True)

    downloader = get_downloader(platform, config, source, db)
    downloader.download_single(post_id)


def main():
    parser = argparse.ArgumentParser(
        description='Бэкап статей с Sponsr и Boosty',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Примеры:
  %(prog)s                                    # синхронизация по конфигу
  %(prog)s "https://sponsr.ru/author/123/..." # скачать один пост
  %(prog)s "https://boosty.to/author/posts/uuid"
        '''
    )

    parser.add_argument(
        'url',
        nargs='?',
        help='URL поста для скачивания (опционально)'
    )

    parser.add_argument(
        '-c', '--config',
        type=Path,
        default=Path('config.yaml'),
        help='Путь к конфигу (по умолчанию: config.yaml)'
    )

    args = parser.parse_args()

    # Загружаем конфиг
    if not args.config.exists():
        print(f"Ошибка: конфиг не найден: {args.config}")
        print("Создайте config.yaml по образцу.")
        sys.exit(1)

    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Ошибка загрузки конфига: {e}")
        sys.exit(1)

    # Создаём директорию и базу
    config.output_dir.mkdir(parents=True, exist_ok=True)
    db = Database(config.output_dir / 'index.db')

    # Выполняем команду
    if args.url:
        if not is_post_url(args.url):
            print(f"Ошибка: неверный URL поста: {args.url}")
            sys.exit(1)
        download_single_post(args.url, config, db)
    else:
        if not config.sources:
            print("Нет источников в конфиге. Добавьте секцию 'sources'.")
            sys.exit(1)
        sync_all(config, db)

    print("\nГотово!")


if __name__ == '__main__':
    main()
