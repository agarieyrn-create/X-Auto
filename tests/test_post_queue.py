"""
tests/test_post_queue.py
=========================
PostQueue の単体テスト
"""

import os
import tempfile
import pytest
from datetime import datetime, timedelta

# テスト用に DB を一時ファイルに向ける
@pytest.fixture
def queue():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # config.DB_PATH を上書き
    import config
    original = config.DB_PATH
    config.DB_PATH = db_path

    from core.post_queue import PostQueue
    q = PostQueue(db_path=db_path)
    yield q

    config.DB_PATH = original
    os.unlink(db_path)


def _make_post(text="テスト投稿", category="howto", offset_minutes=0) -> dict:
    scheduled = (datetime.now() + timedelta(minutes=offset_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return {
        "text": text,
        "category": category,
        "scheduled_at": scheduled,
        "day_index": 1,
        "slot_index": 1,
    }


class TestPostQueue:
    def test_add_and_count(self, queue):
        posts = [_make_post(f"投稿{i}") for i in range(5)]
        n = queue.add_posts(posts)
        assert n == 5
        assert queue.get_pending_count() == 5

    def test_get_due_posts_future(self, queue):
        # 未来のスケジュール → due ではない
        future_post = _make_post("未来の投稿", offset_minutes=60)
        queue.add_posts([future_post])
        due = queue.get_due_posts()
        assert len(due) == 0

    def test_get_due_posts_past(self, queue):
        # 過去のスケジュール → due
        past_post = _make_post("過去の投稿", offset_minutes=-1)
        queue.add_posts([past_post])
        due = queue.get_due_posts()
        assert len(due) == 1
        assert due[0]["text"] == "過去の投稿"

    def test_mark_posted(self, queue):
        queue.add_posts([_make_post("投稿テスト")])
        pending = queue.get_all_pending()
        assert len(pending) == 1

        post_id = pending[0]["id"]
        queue.mark_posted(post_id, tweet_id="12345")

        summary = queue.get_posts_summary()
        assert summary["posted"] == 1
        assert summary["pending"] == 0

    def test_mark_failed(self, queue):
        queue.add_posts([_make_post("失敗テスト")])
        pending = queue.get_all_pending()
        post_id = pending[0]["id"]
        queue.mark_failed(post_id, error_msg="テストエラー")

        summary = queue.get_posts_summary()
        assert summary["failed"] == 1

    def test_get_next_pending(self, queue):
        queue.add_posts([_make_post("最初の投稿")])
        next_post = queue.get_next_pending()
        assert next_post is not None
        assert next_post["text"] == "最初の投稿"

    def test_empty_queue_returns_none(self, queue):
        assert queue.get_next_pending() is None

    def test_summary_defaults(self, queue):
        summary = queue.get_posts_summary()
        assert summary["pending"] == 0
        assert summary["posted"] == 0
        assert summary["failed"] == 0
