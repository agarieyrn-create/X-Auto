"""
agents/profile_analyzer.py  ── プロファイル分析エージェント
============================================================
役割:
  XアナリティクスのCSVを読み込み、Claudeを使ってアカウントの
  AI人格プロファイルを自動生成する。

責任範囲:
  ✅ CSVのパース・前処理
  ✅ 伸びた投稿トップNの抽出
  ✅ Claudeへの分析依頼
  ✅ account_profile.py の生成・出力
  ❌ 投稿生成・投稿・スケジューリング (他エージェントの責務)
"""

import csv
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from core.claude_client import ClaudeClient
import config

logger = logging.getLogger(__name__)

# 分析に使う上位投稿数
TOP_N_POSTS = 50


class ProfileAnalyzerAgent:
    """
    CSVデータを分析してAI人格プロファイルを生成するエージェント。
    このエージェントは Claude API を直接呼び出し、
    account_profile.py を書き出す。
    """

    def __init__(self, claude: Optional[ClaudeClient] = None):
        self._claude = claude or ClaudeClient()

    # ── パブリックAPI ─────────────────────────────────────

    def analyze_csv(self, csv_path: str, output_path: str = config.PROFILE_PATH) -> dict:
        """
        CSVを分析してプロファイルを生成・保存する。

        Args:
            csv_path:    XアナリティクスのCSVファイルパス
            output_path: 出力先 (account_profile.py)

        Returns:
            生成された ACCOUNT_PROFILE dict
        """
        logger.info("プロファイル分析開始: %s", csv_path)

        posts = self._parse_csv(csv_path)
        if not posts:
            raise ValueError(f"CSVからデータを読み込めませんでした: {csv_path}")

        logger.info("CSVから%d件の投稿を読み込みました", len(posts))

        top_posts    = self._get_top_posts(posts, n=TOP_N_POSTS)
        recent_posts = posts[:100]  # 口調分析用に直近100件

        profile_dict = self._generate_profile(top_posts, recent_posts)
        self._save_profile(profile_dict, output_path)

        logger.info("プロファイルを保存しました: %s", output_path)
        return profile_dict

    # ── CSV パース ────────────────────────────────────────

    def _parse_csv(self, csv_path: str) -> list[dict]:
        """
        XアナリティクスCSVをパースする。
        ヘッダー列名が英語・日本語どちらでも対応。
        """
        posts = []
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                text = (
                    row.get("Tweet text")
                    or row.get("ツイートテキスト")
                    or row.get("Post text")
                    or ""
                ).strip()

                if not text or text.startswith("RT "):
                    continue  # リツイートはスキップ

                def _int(key_candidates):
                    for k in key_candidates:
                        v = row.get(k, "").replace(",", "").strip()
                        if v.isdigit():
                            return int(v)
                    return 0

                impressions = _int(["impressions", "Impressions", "インプレッション数"])
                engagements = _int(["engagements", "Engagements", "エンゲージメント"])
                likes       = _int(["likes", "Likes", "いいね数", "Like"])
                bookmarks   = _int(["bookmarks", "Bookmarks", "ブックマーク数"])

                posts.append({
                    "text":        text,
                    "impressions": impressions,
                    "engagements": engagements,
                    "likes":       likes,
                    "bookmarks":   bookmarks,
                    "score":       impressions + (engagements * 5) + (likes * 3) + (bookmarks * 10),
                })

        return posts

    def _get_top_posts(self, posts: list[dict], n: int) -> list[dict]:
        """スコアが高い順にn件返す。"""
        return sorted(posts, key=lambda p: p["score"], reverse=True)[:n]

    # ── プロファイル生成 ──────────────────────────────────

    def _generate_profile(
        self,
        top_posts: list[dict],
        recent_posts: list[dict],
    ) -> dict:
        """Claude を使ってプロファイルを生成する。"""

        top_text    = self._format_posts_for_prompt(top_posts, label="【高エンゲージメント投稿】")
        recent_text = self._format_posts_for_prompt(recent_posts, label="【直近の投稿サンプル】")

        system = """あなたはSNSアカウントの文章スタイルを分析する専門家です。
提供された投稿データから、アカウントのAI人格プロファイルを正確に抽出してください。
出力はJSON形式のみで、説明文は一切含めないでください。"""

        prompt = f"""以下のXアカウントの投稿データを分析して、AI人格プロファイルをJSON形式で出力してください。

{top_text}

{recent_text}

以下のJSON構造で出力してください（コードブロックなし、JSONのみ）:

{{
  "account_name": "分析したアカウントの特徴を表す名前（不明な場合は空文字）",
  "theme": "アカウントの主要テーマ（例: AI・自動化・副業）",
  "tone": {{
    "style": "口調のスタイル（例: カジュアル、セミプロ、ビジネス）",
    "sentence_end": ["特徴的な語尾パターンのリスト"],
    "characteristics": ["文体の特徴リスト（5〜8個）"],
    "avoid": ["使わない表現リスト（3〜5個）"]
  }},
  "values": ["繰り返し語られている価値観・メッセージリスト（5〜8個）"],
  "achievements": ["投稿内で言及されている実績・数字リスト"],
  "category_ratio": {{
    "howto": 0.35,
    "provocation": 0.25,
    "result": 0.20,
    "tool": 0.10,
    "mindset": 0.10
  }},
  "winning_patterns": [
    {{
      "name": "パターン名",
      "description": "このパターンの説明",
      "example_structure": "投稿の構成説明"
    }}
  ],
  "constraints": ["投稿生成時に守るべき制約リスト"]
}}

重要:
- 実際の投稿から読み取れる事実のみを記載してください
- 実績・数字は投稿内で実際に言及されているものだけを記載してください
- カテゴリ比率は実際の投稿の内訳を反映してください（合計が1.0になるように）"""

        raw = self._claude.chat(
            prompt=prompt,
            system=system,
            model=config.CLAUDE_PROFILE_MODEL,
            max_tokens=3000,
        )

        return self._parse_json_response(raw)

    def _format_posts_for_prompt(self, posts: list[dict], label: str) -> str:
        lines = [label]
        for i, p in enumerate(posts, 1):
            score_info = (
                f"(インプレ:{p['impressions']:,} "
                f"いいね:{p['likes']:,} "
                f"エンゲ:{p['engagements']:,})"
            ) if p.get("impressions") else ""
            lines.append(f"{i}. {p['text']} {score_info}")
        return "\n".join(lines)

    def _parse_json_response(self, raw: str) -> dict:
        """Claudeの応答からJSONを取り出す。"""
        # コードブロックを除去
        cleaned = re.sub(r"```json\s*|\s*```", "", raw).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("JSON パース失敗: %s\n応答: %s", e, raw[:500])
            raise ValueError(f"プロファイルのJSONが不正です: {e}") from e

    # ── ファイル保存 ──────────────────────────────────────

    def _save_profile(self, profile: dict, output_path: str):
        """ACCOUNT_PROFILE = {...} 形式で Python ファイルに書き出す。"""
        import json as _json

        profile_str = _json.dumps(profile, ensure_ascii=False, indent=4)
        content = f'''"""
AI人格プロファイル (account_profile.py)
=========================================
このファイルはProfileAnalyzerAgentが自動生成しました。
手動で編集することも可能です。
"""

ACCOUNT_PROFILE = {profile_str}
'''
        Path(output_path).write_text(content, encoding="utf-8")
