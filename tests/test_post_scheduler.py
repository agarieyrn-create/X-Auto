"""
tests/test_post_scheduler.py
==============================
PostSchedulerAgent の単体テスト（TwitterClient をモック）
"""

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from core.post_queue import PostQueue


@pytest.fixture
def queue():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    q = PostQueue(db_path=db_path)
    yield q
    os.unlink(db_path)


@pytest.fixture
def mock_twitter_ok():
    """投稿成功するモック Twitter クライアント。"""
    client = MagicMock()
    client.post_tweet.return_value = {
        "ok": True,
        "tweet_id": "9999999",
        "error": "",
    }
    return client


@pytest.fixture
def mock_twitter_fail():
    """投稿失敗するモック Twitter クライアント。"""
    client = MagicMock()
    client.post_tweet.return_value = {
        "ok": False,
        "tweet_id": "",
        "error": "テストエラー",
    }
    return client


def _add_post(queue, text="テスト投稿です", offset_minutes=-1):
    scheduled = (datetime.now() + timedelta(minutes=offset_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    queue.add_posts([{
        "text": text,
        "category": "howto",
        "scheduled_at": scheduled,
        "day_index": 1,
        "slot_index": 1,
    }])


class TestPostSchedulerAgent:
    def test_post_one_success(self, queue, mock_twitter_ok):
        from agents.post_scheduler import PostSchedulerAgent

        _add_post(queue)
        scheduler = PostSchedulerAgent(queue=queue, twitter=mock_twitter_ok)
        result = scheduler.post_one()

        assert result["ok"] is True
        assert result["tweet_id"] == "9999999"
        assert queue.get_posts_summary()["posted"] == 1

    def test_post_one_failure(self, queue, mock_twitter_fail):
        from agents.post_scheduler import PostSchedulerAgent

        _add_post(queue)
        scheduler = PostSchedulerAgent(queue=queue, twitter=mock_twitter_fail)
        result = scheduler.post_one()

        assert result["ok"] is False
        assert queue.get_posts_summary()["failed"] == 1

    def test_post_one_empty_queue(self, queue, mock_twitter_ok):
        from agents.post_scheduler import PostSchedulerAgent

        scheduler = PostSchedulerAgent(queue=queue, twitter=mock_twitter_ok)
        result = scheduler.post_one()

        assert result["ok"] is False
        assert "キューが空" in result["error"]

    def test_run_once_processes_due(self, queue, mock_twitter_ok):
        from agents.post_scheduler import PostSchedulerAgent

        # 過去スケジュール（due）を2件追加
        _add_post(queue, "投稿1", offset_minutes=-5)
        _add_post(queue, "投稿2", offset_minutes=-2)
        # 未来スケジュール（due でない）を1件追加
        _add_post(queue, "投稿3", offset_minutes=60)

        scheduler = PostSchedulerAgent(queue=queue, twitter=mock_twitter_ok)
        results = scheduler.run_once()

        assert len(results) == 2
        assert all(r["ok"] for r in results)
        summary = queue.get_posts_summary()
        assert summary["posted"] == 2
        assert summary["pending"] == 1
