"""
tests/test_replenishment_agent.py
===================================
ReplenishmentAgent の単体テスト
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


def _add_pending(queue, n=5):
    posts = []
    for i in range(n):
        scheduled = (datetime.now() + timedelta(days=i+1)).strftime("%Y-%m-%d %H:%M:%S")
        posts.append({
            "text": f"テスト投稿 {i+1}",
            "category": "howto",
            "scheduled_at": scheduled,
            "day_index": i + 1,
            "slot_index": 1,
        })
    queue.add_posts(posts)


class TestReplenishmentAgent:
    def test_no_replenish_when_above_threshold(self, queue):
        """閾値以上のキューがある場合は補充しない。"""
        from agents.replenishment_agent import ReplenishmentAgent

        _add_pending(queue, n=20)
        mock_gen = MagicMock()
        agent = ReplenishmentAgent(queue=queue, generator=mock_gen, threshold=7)

        # last_check を昔にリセットして確実にチェックさせる
        agent._last_check = datetime.min
        result = agent.check_and_replenish()

        assert result is False
        mock_gen.generate_bulk.assert_not_called()

    def test_replenish_when_below_threshold(self, queue):
        """閾値以下のキューがある場合は補充する。"""
        from agents.replenishment_agent import ReplenishmentAgent

        _add_pending(queue, n=3)
        mock_gen = MagicMock()
        mock_gen.generate_bulk.return_value = [{"text": "新しい投稿"}] * 21

        agent = ReplenishmentAgent(queue=queue, generator=mock_gen, threshold=7)
        agent._last_check = datetime.min
        result = agent.check_and_replenish()

        assert result is True
        mock_gen.generate_bulk.assert_called_once()

    def test_force_replenish(self, queue):
        """force_replenish は閾値関係なく実行される。"""
        from agents.replenishment_agent import ReplenishmentAgent

        _add_pending(queue, n=20)
        mock_gen = MagicMock()
        mock_gen.generate_bulk.return_value = [{"text": "新しい投稿"}] * 21

        agent = ReplenishmentAgent(queue=queue, generator=mock_gen, threshold=7)
        agent.force_replenish(days=7)

        mock_gen.generate_bulk.assert_called_once_with(
            days=7, start_date=pytest.approx(agent._calc_start_date(), abs=60)
        )

    def test_throttle_check(self, queue):
        """1時間以内の再チェックは実行しない。"""
        from agents.replenishment_agent import ReplenishmentAgent

        _add_pending(queue, n=1)  # 閾値以下
        mock_gen = MagicMock()
        agent = ReplenishmentAgent(queue=queue, generator=mock_gen, threshold=7)

        # 最初のチェック（成功するはず）
        agent._last_check = datetime.min
        agent.check_and_replenish()

        # すぐに再チェック（スロットルされるはず）
        result = agent.check_and_replenish()
        assert result is False
        # generate_bulk は1回しか呼ばれていない
        assert mock_gen.generate_bulk.call_count == 1
