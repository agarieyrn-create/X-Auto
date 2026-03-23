"""
core/post_queue.py
===================
投稿キュー管理 (SQLite)
- 生成済み投稿の永続化
- スケジュール管理・ステータス管理
- スレッドセーフな操作
"""

import sqlite3
import threading
import logging
from datetime import datetime, date
from typing import Optional
from contextlib import contextmanager

import config

logger = logging.getLogger(__name__)

# ── ステータス定数 ────────────────────────────────────────
STATUS_PENDING  = "pending"   # 投稿待ち
STATUS_POSTED   = "posted"    # 投稿済み
STATUS_FAILED   = "failed"    # 失敗
STATUS_SKIPPED  = "skipped"   # スキップ（手動）


class PostQueue:
    """
    SQLite ベースの投稿キュー。
    スレッドセーフ（接続をスレッドごとに生成）。
    """

    def __init__(self, db_path: str = config.DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # ── 内部ヘルパー ──────────────────────────────────────

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """テーブルを初期化する（初回のみ作成）。"""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    text          TEXT    NOT NULL,
                    category      TEXT    NOT NULL DEFAULT 'howto',
                    scheduled_at  TEXT,          -- ISO8601 例: "2024-01-15 08:00:00"
                    posted_at     TEXT,          -- 実際に投稿した日時
                    tweet_id      TEXT,          -- X から返ってきたツイートID
                    status        TEXT    NOT NULL DEFAULT 'pending',
                    day_index     INTEGER,       -- 何日目の投稿か (1始まり)
                    slot_index    INTEGER,       -- 1日の何番目か (1始まり)
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                    error_msg     TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS generation_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    generated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    count       INTEGER NOT NULL,
                    note        TEXT
                )
            """)
        logger.debug("DB初期化完了: %s", self._db_path)

    # ── 書き込み ──────────────────────────────────────────

    def add_posts(self, posts: list[dict]) -> int:
        """
        投稿リストをキューに追加する。

        Args:
            posts: [{"text": str, "category": str, "scheduled_at": str,
                     "day_index": int, "slot_index": int}, ...]

        Returns:
            追加件数
        """
        with self._lock:
            with self._conn() as conn:
                conn.executemany("""
                    INSERT INTO posts (text, category, scheduled_at, day_index, slot_index)
                    VALUES (:text, :category, :scheduled_at, :day_index, :slot_index)
                """, posts)
                conn.execute(
                    "INSERT INTO generation_log (count, note) VALUES (?, ?)",
                    (len(posts), f"{len(posts)}件追加")
                )
        logger.info("%d件の投稿をキューに追加しました", len(posts))
        return len(posts)

    def mark_posted(self, post_id: int, tweet_id: str, posted_at: Optional[str] = None):
        """投稿済みとしてマークする。"""
        _posted_at = posted_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    UPDATE posts
                    SET status='posted', tweet_id=?, posted_at=?
                    WHERE id=?
                """, (tweet_id, _posted_at, post_id))

    def mark_failed(self, post_id: int, error_msg: str):
        """失敗としてマークする。"""
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    UPDATE posts
                    SET status='failed', error_msg=?
                    WHERE id=?
                """, (error_msg, post_id))

    # ── 読み取り ──────────────────────────────────────────

    def get_pending_count(self) -> int:
        """投稿待ち件数を返す。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM posts WHERE status='pending'"
            ).fetchone()
            return row["cnt"]

    def get_due_posts(self, now: Optional[datetime] = None) -> list[dict]:
        """
        現時刻以前にスケジュールされた未投稿の投稿を返す。
        recovery モードでは scheduled_at が RECOVERY_WINDOW_HOURS 以内のものも含む。
        """
        _now = now or datetime.now()
        now_str = _now.strftime("%Y-%m-%d %H:%M:%S")

        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM posts
                WHERE status='pending'
                  AND scheduled_at IS NOT NULL
                  AND scheduled_at <= ?
                ORDER BY scheduled_at ASC
            """, (now_str,)).fetchall()

        return [dict(r) for r in rows]

    def get_post_by_id(self, post_id: int) -> Optional[dict]:
        """IDで投稿を1件取得する（O(1) DB クエリ）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM posts WHERE id=? AND status='pending'", (post_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_next_pending(self) -> Optional[dict]:
        """スケジュールなしも含む次の pending 投稿を返す（テスト投稿用）。"""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM posts
                WHERE status='pending'
                ORDER BY id ASC
                LIMIT 1
            """).fetchone()
        return dict(row) if row else None

    def get_posts_summary(self) -> dict:
        """キューの概要を返す。"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT status, COUNT(*) as cnt FROM posts GROUP BY status
            """).fetchall()
        summary = {r["status"]: r["cnt"] for r in rows}
        summary.setdefault("pending", 0)
        summary.setdefault("posted", 0)
        summary.setdefault("failed", 0)
        return summary

    def get_recent_posts(self, limit: int = 7) -> list[dict]:
        """直近の投稿済みリストを返す（重複チェック用）。"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT text FROM posts
                WHERE status='posted'
                ORDER BY posted_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_all_pending(self) -> list[dict]:
        """全ての pending 投稿を返す（確認・修正用）。"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM posts
                WHERE status='pending'
                ORDER BY scheduled_at ASC, id ASC
            """).fetchall()
        return [dict(r) for r in rows]
