# src/database.py
"""SQLite операции для индекса постов."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PostRecord:
    platform: str
    author: str
    post_id: str
    title: str
    slug: str
    post_date: str
    source_url: str
    local_path: str
    tags: str
    synced_at: str


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Возвращает соединение, создавая его при необходимости."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self):
        """Создаёт таблицы, если не существуют."""
        conn = self._get_conn()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                author TEXT NOT NULL,
                post_id TEXT NOT NULL,
                title TEXT,
                slug TEXT,
                post_date TEXT,
                source_url TEXT,
                local_path TEXT,
                tags TEXT,
                synced_at TEXT,
                UNIQUE(platform, author, post_id)
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_platform_author
            ON posts(platform, author)
        ''')
        conn.commit()

    def close(self):
        """Закрывает соединение с БД."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def post_exists(self, platform: str, author: str, post_id: str) -> bool:
        """Проверяет, существует ли пост в индексе."""
        conn = self._get_conn()
        cursor = conn.execute(
            'SELECT 1 FROM posts WHERE platform = ? AND author = ? AND post_id = ?',
            (platform, author, post_id)
        )
        return cursor.fetchone() is not None

    def add_post(self, record: PostRecord):
        """Добавляет пост в индекс."""
        conn = self._get_conn()
        conn.execute('''
            INSERT OR REPLACE INTO posts
            (platform, author, post_id, title, slug, post_date, source_url, local_path, tags, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            record.platform,
            record.author,
            record.post_id,
            record.title,
            record.slug,
            record.post_date,
            record.source_url,
            record.local_path,
            record.tags,
            record.synced_at,
        ))
        conn.commit()

    def get_post(self, platform: str, author: str, post_id: str) -> PostRecord | None:
        """Получает пост из индекса."""
        conn = self._get_conn()
        cursor = conn.execute(
            'SELECT * FROM posts WHERE platform = ? AND author = ? AND post_id = ?',
            (platform, author, post_id)
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_record(row)
        return None

    def get_all_post_ids(self, platform: str, author: str) -> set[str]:
        """Возвращает множество всех post_id для автора."""
        conn = self._get_conn()
        cursor = conn.execute(
            'SELECT post_id FROM posts WHERE platform = ? AND author = ?',
            (platform, author)
        )
        return {row[0] for row in cursor.fetchall()}

    def get_post_count(self, platform: str, author: str) -> int:
        """Возвращает количество постов автора."""
        conn = self._get_conn()
        cursor = conn.execute(
            'SELECT COUNT(*) FROM posts WHERE platform = ? AND author = ?',
            (platform, author)
        )
        return cursor.fetchone()[0]

    def get_post_by_source_url(self, url: str) -> PostRecord | None:
        """Ищет пост по исходному URL."""
        conn = self._get_conn()
        cursor = conn.execute(
            'SELECT * FROM posts WHERE source_url = ?',
            (url,)
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_record(row)
        return None

    def get_all_posts(self, platform: str, author: str) -> list[PostRecord]:
        """Возвращает все посты автора."""
        conn = self._get_conn()
        cursor = conn.execute(
            'SELECT * FROM posts WHERE platform = ? AND author = ?',
            (platform, author)
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def _row_to_record(self, row: sqlite3.Row) -> PostRecord:
        """Конвертирует строку БД в PostRecord."""
        return PostRecord(
            platform=row['platform'],
            author=row['author'],
            post_id=row['post_id'],
            title=row['title'],
            slug=row['slug'],
            post_date=row['post_date'],
            source_url=row['source_url'],
            local_path=row['local_path'],
            tags=row['tags'],
            synced_at=row['synced_at'],
        )
