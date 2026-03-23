"""
tests/test_profile_analyzer.py
================================
ProfileAnalyzerAgent の単体テスト（Claude API をモック）
"""

import csv
import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sample_csv():
    """サンプルXアナリティクスCSVを作成する。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Tweet text", "impressions", "engagements", "likes", "bookmarks"
            ],
        )
        writer.writeheader()
        # 通常の投稿
        writer.writerow({
            "Tweet text": "AIで稼ぐ時代が来た。早く動いた人が勝つ。",
            "impressions": "10000",
            "engagements": "500",
            "likes": "300",
            "bookmarks": "50",
        })
        writer.writerow({
            "Tweet text": "毎日3時間作業すれば、1年後には別人になれる。",
            "impressions": "5000",
            "engagements": "200",
            "likes": "150",
            "bookmarks": "20",
        })
        # RTはスキップされるはず
        writer.writerow({
            "Tweet text": "RT @someone: これはリツイートです",
            "impressions": "100",
            "engagements": "0",
            "likes": "0",
            "bookmarks": "0",
        })
        csv_path = f.name

    yield csv_path

    if os.path.exists(csv_path):
        os.unlink(csv_path)


@pytest.fixture
def mock_claude():
    """Claude クライアントのモック。有効なプロファイルJSONを返す。"""
    client = MagicMock()
    profile = {
        "account_name": "テストアカウント",
        "theme": "AI・ビジネス",
        "tone": {
            "style": "カジュアル",
            "sentence_end": ["です。", "ます。"],
            "characteristics": ["短文", "問いかけ"],
            "avoid": ["難しい専門用語"],
        },
        "values": ["行動量が重要", "AIを使いこなせ"],
        "achievements": ["月収100万円達成"],
        "category_ratio": {
            "howto": 0.35,
            "provocation": 0.25,
            "result": 0.20,
            "tool": 0.10,
            "mindset": 0.10,
        },
        "winning_patterns": [
            {
                "name": "問題提起型",
                "description": "問題を提起して解決策を示す",
                "example_structure": "問題→解決→CTA",
            }
        ],
        "constraints": ["140文字以内"],
    }
    client.chat.return_value = json.dumps(profile, ensure_ascii=False)
    return client


class TestProfileAnalyzerAgent:
    def test_parse_csv_filters_rt(self, sample_csv):
        """RTが除外され、通常の投稿だけが取り込まれる。"""
        from agents.profile_analyzer import ProfileAnalyzerAgent

        agent = ProfileAnalyzerAgent.__new__(ProfileAnalyzerAgent)
        posts = agent._parse_csv(sample_csv)

        assert len(posts) == 2
        assert all("RT" not in p["text"] for p in posts)

    def test_parse_csv_scores_calculated(self, sample_csv):
        """スコアが正しく計算される。"""
        from agents.profile_analyzer import ProfileAnalyzerAgent

        agent = ProfileAnalyzerAgent.__new__(ProfileAnalyzerAgent)
        posts = agent._parse_csv(sample_csv)

        for p in posts:
            assert "score" in p
            assert p["score"] > 0

        # インプレッションが多い方がスコアが高い
        sorted_posts = sorted(posts, key=lambda x: x["score"], reverse=True)
        assert sorted_posts[0]["impressions"] == 10000

    def test_analyze_csv_creates_profile(self, sample_csv, mock_claude, tmp_path):
        """analyze_csv がプロファイルファイルを作成する。"""
        from agents.profile_analyzer import ProfileAnalyzerAgent

        output_path = str(tmp_path / "test_profile.py")
        agent = ProfileAnalyzerAgent(claude=mock_claude)
        profile = agent.analyze_csv(sample_csv, output_path=output_path)

        assert "theme" in profile
        assert "tone" in profile
        assert os.path.exists(output_path)

        content = open(output_path, encoding="utf-8").read()
        assert "ACCOUNT_PROFILE" in content

    def test_parse_json_response_strips_code_block(self):
        """コードブロックで囲まれたJSONも正しくパースされる。"""
        from agents.profile_analyzer import ProfileAnalyzerAgent

        agent = ProfileAnalyzerAgent.__new__(ProfileAnalyzerAgent)
        raw = '```json\n{"key": "value"}\n```'
        result = agent._parse_json_response(raw)
        assert result == {"key": "value"}
