"""
tests/test_post_generator.py
==============================
PostGeneratorAgent の単体テスト（Claude API をモック）
"""

import os
import tempfile
from datetime import datetime
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


@pytest.fixture
def mock_claude():
    """Claude クライアントのモック。番号付き投稿を返す。"""
    client = MagicMock()
    # 21件の投稿を返す（各行を改行で区切り、80文字以上の文章にする）
    lines = [
        f"{i+1}. AIを活用して自分の時間を取り戻す方法を実践して3ヶ月。驚くほど毎日が変わった。具体的な手順は今すぐ試せる。番号{i+1}。"
        for i in range(21)
    ]
    client.chat.return_value = "\n".join(lines)
    return client


class TestPostGeneratorAgent:
    def test_assign_categories_sum(self):
        """カテゴリ割り当ての合計が要求件数と一致する。"""
        import config
        from agents.post_generator import PostGeneratorAgent

        agent = PostGeneratorAgent.__new__(PostGeneratorAgent)
        agent._profile = {}
        cats = agent._assign_categories(21)
        assert len(cats) == 21

    def test_generate_bulk_adds_to_queue(self, queue, mock_claude):
        """generate_bulk が PostQueue に正しく追加される。"""
        from agents.post_generator import PostGeneratorAgent

        agent = PostGeneratorAgent(queue=queue, claude=mock_claude)
        agent._profile = {
            "theme": "テスト",
            "tone": {},
            "values": [],
            "winning_patterns": [],
            "constraints": [],
        }

        posts = agent.generate_bulk(days=7)
        assert len(posts) > 0
        assert queue.get_pending_count() == len(posts)

    def test_parse_posts_extracts_text(self):
        """_parse_posts が番号付きテキストを正しく抽出する。"""
        from agents.post_generator import PostGeneratorAgent

        agent = PostGeneratorAgent.__new__(PostGeneratorAgent)
        agent._profile = {}

        raw = (
            "1. AIを活用して自分の時間を取り戻す方法を実践して3ヶ月。驚くほど毎日が変わった。具体的な手順は今すぐ試せる。\n"
            "2. 毎日3時間の作業を自動化したら、気づいたら収益が3倍になっていた。仕組みを作った人が勝つ時代。"
        )
        posts = agent._parse_posts(raw, expected=2)
        assert len(posts) == 2
        assert "AIを活用" in posts[0]

    def test_schedule_calculation(self, queue, mock_claude):
        """スケジュール日時が正しく計算される。"""
        import config
        from agents.post_generator import PostGeneratorAgent

        config.POST_SCHEDULE = ["08:00", "12:30", "19:00"]

        agent = PostGeneratorAgent(queue=queue, claude=mock_claude)
        agent._profile = {}

        start = datetime(2024, 1, 15)
        posts = agent.generate_bulk(days=1, start_date=start)

        scheduled_times = [p["scheduled_at"] for p in posts]
        assert any("08:00" in t for t in scheduled_times)
        assert any("12:30" in t for t in scheduled_times)
        assert any("19:00" in t for t in scheduled_times)
