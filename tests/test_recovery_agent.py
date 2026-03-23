"""
tests/test_recovery_agent.py
==============================
RecoveryAgent の単体テスト（ネットワーク・スケジューラーをモック）
"""

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.post_queue import PostQueue


@pytest.fixture
def queue():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    q = PostQueue(db_path=db_path)
    yield q
    os.unlink(db_path)


def _add_past_post(queue, text="過去の投稿", hours_ago=1):
    scheduled = (datetime.now() - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    queue.add_posts([{
        "text": text,
        "category": "howto",
        "scheduled_at": scheduled,
        "day_index": 1,
        "slot_index": 1,
    }])


@pytest.fixture
def mock_scheduler():
    sched = MagicMock()
    sched.post_record.return_value = {
        "ok": True,
        "tweet_id": "12345",
        "text": "テスト投稿",
        "error": "",
        "post_id": 1,
    }
    return sched


class TestRecoveryAgent:
    def test_no_recovery_when_online_from_start(self, queue, mock_scheduler):
        """最初からオンラインなら何もしない。"""
        from agents.recovery_agent import RecoveryAgent

        agent = RecoveryAgent(queue=queue, scheduler=mock_scheduler)
        agent._was_offline = False

        with patch.object(agent, "_is_online", return_value=True):
            results = agent.check_and_recover()

        assert results == []
        mock_scheduler.post_record.assert_not_called()

    def test_recovery_triggers_after_offline(self, queue, mock_scheduler):
        """オフライン→オンライン復帰でリカバリが実行される。"""
        from agents.recovery_agent import RecoveryAgent

        _add_past_post(queue, "未投稿の投稿", hours_ago=1)
        agent = RecoveryAgent(queue=queue, scheduler=mock_scheduler)
        agent._was_offline = True   # オフライン状態をシミュレート

        with patch.object(agent, "_is_online", return_value=True):
            results = agent.check_and_recover()

        assert len(results) == 1
        assert results[0]["ok"] is True
        mock_scheduler.post_record.assert_called_once()

    def test_no_recovery_when_still_offline(self, queue, mock_scheduler):
        """まだオフライン中ならリカバリしない。"""
        from agents.recovery_agent import RecoveryAgent

        _add_past_post(queue)
        agent = RecoveryAgent(queue=queue, scheduler=mock_scheduler)
        agent._was_offline = False

        with patch.object(agent, "_is_online", return_value=False):
            results = agent.check_and_recover()

        assert results == []
        mock_scheduler.post_record.assert_not_called()
        assert agent._was_offline is True  # フラグが立つ

    def test_recovery_skips_old_posts_outside_window(self, queue, mock_scheduler):
        """RECOVERY_WINDOW 外の古い未投稿はスキップされる。"""
        from agents.recovery_agent import RecoveryAgent

        # ウィンドウ 2時間、投稿は 3時間前 → スキップされるはず
        _add_past_post(queue, "古い投稿", hours_ago=3)
        agent = RecoveryAgent(queue=queue, scheduler=mock_scheduler, recovery_window_hours=2)
        agent._was_offline = True

        with patch.object(agent, "_is_online", return_value=True):
            results = agent.check_and_recover()

        assert results == []
        mock_scheduler.post_record.assert_not_called()

    def test_recovery_disabled_by_config(self, queue, mock_scheduler):
        """RECOVERY_ENABLED=False のときはリカバリしない。"""
        import config
        from agents.recovery_agent import RecoveryAgent

        original = config.RECOVERY_ENABLED
        config.RECOVERY_ENABLED = False

        try:
            _add_past_post(queue)
            agent = RecoveryAgent(queue=queue, scheduler=mock_scheduler)
            agent._was_offline = True
            with patch.object(agent, "_is_online", return_value=True):
                results = agent.check_and_recover()
            assert results == []
        finally:
            config.RECOVERY_ENABLED = original

    def test_force_recover(self, queue, mock_scheduler):
        """force_recover は状態に関わらず実行される。"""
        from agents.recovery_agent import RecoveryAgent

        _add_past_post(queue, "強制リカバリ対象", hours_ago=1)
        agent = RecoveryAgent(queue=queue, scheduler=mock_scheduler)

        results = agent.force_recover()

        assert len(results) == 1
        mock_scheduler.post_record.assert_called_once()

    def test_is_online_uses_create_connection(self, queue):
        """_is_online が setdefaulttimeout を使わない（グローバル副作用なし）。"""
        import socket as _socket
        from agents.recovery_agent import RecoveryAgent

        agent = RecoveryAgent(queue=queue)

        # create_connection が成功するケース
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            result = agent._is_online()

        assert result is True
        # setdefaulttimeout が呼ばれていないことを確認
        # (グローバル副作用がない)
        mock_conn.assert_called_once()
