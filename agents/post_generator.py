"""
agents/post_generator.py  ── 投稿生成エージェント
====================================================
役割:
  AI人格プロファイルを読み込み、Claudeを使って
  指定日数分の投稿文を一括生成し、PostQueueに追加する。

責任範囲:
  ✅ プロファイルの読み込み・プロンプト構築
  ✅ カテゴリ比率に従った投稿割り当て
  ✅ スケジュール日時の計算
  ✅ 生成された投稿の品質チェック
  ✅ PostQueue への登録
  ❌ 投稿の実行・スケジューリング (PostSchedulerAgent の責務)
"""

import importlib
import json
import logging
import random
import re
from datetime import datetime, timedelta
from typing import Optional

from core.claude_client import ClaudeClient
from core.post_queue import PostQueue
import config

logger = logging.getLogger(__name__)


class PostGeneratorAgent:
    """
    AI人格プロファイルを使ってXの投稿文を生成するエージェント。
    生成結果は PostQueue に書き込む。
    """

    def __init__(
        self,
        queue: Optional[PostQueue] = None,
        claude: Optional[ClaudeClient] = None,
    ):
        self._queue  = queue  or PostQueue()
        self._claude = claude or ClaudeClient()
        self._profile = self._load_profile()

    # ── パブリックAPI ─────────────────────────────────────

    def generate_bulk(
        self,
        days: int = 7,
        start_date: Optional[datetime] = None,
    ) -> list[dict]:
        """
        指定日数分の投稿を一括生成してキューに追加する。

        Args:
            days:       生成する日数
            start_date: 開始日 (省略時は翌日)

        Returns:
            生成された投稿リスト
        """
        _start = start_date or (datetime.now() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        total = days * config.POSTS_PER_DAY
        logger.info("%d日分 (%d件) の投稿生成を開始", days, total)

        # カテゴリ割り当て
        categories = self._assign_categories(total)

        # Claudeへ一括生成依頼
        posts_text = self._call_claude_bulk(categories, total)

        # スケジュール計算と構造化
        posts = self._build_post_records(posts_text, categories, _start, days)

        # キューに追加
        self._queue.add_posts(posts)

        logger.info("%d件の投稿をキューに追加しました", len(posts))
        self._print_preview(posts)
        return posts

    # ── プロファイル読み込み ──────────────────────────────

    def _load_profile(self) -> dict:
        """account_profile.py から ACCOUNT_PROFILE を読み込む。"""
        try:
            spec = importlib.util.spec_from_file_location(
                "account_profile", config.PROFILE_PATH
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            profile = module.ACCOUNT_PROFILE
            logger.info("プロファイル読み込み成功: %s", profile.get("theme", ""))
            return profile
        except Exception as e:
            logger.warning("account_profile.py が読み込めません (%s)。デフォルトを使用します。", e)
            return {}

    # ── カテゴリ割り当て ──────────────────────────────────

    def _assign_categories(self, total: int) -> list[str]:
        """
        設定の比率に従ってカテゴリを割り当て、シャッフルする。
        プロファイルのカテゴリ比率が優先される。
        """
        ratio = (
            self._profile.get("category_ratio")
            or config.CATEGORY_RATIO
        )

        # 比率を件数に変換
        counts: dict[str, int] = {}
        assigned = 0
        items = list(ratio.items())
        for cat, r in items[:-1]:
            n = round(total * r)
            counts[cat] = n
            assigned += n
        # 残りを最後のカテゴリに割り当て
        last_cat = items[-1][0]
        counts[last_cat] = total - assigned

        categories = []
        for cat, n in counts.items():
            categories.extend([cat] * n)

        random.shuffle(categories)
        return categories

    # ── Claude 呼び出し ───────────────────────────────────

    def _call_claude_bulk(self, categories: list[str], total: int) -> list[str]:
        """Claude に一括で投稿文を生成させる。"""
        system = self._build_system_prompt()
        prompt = self._build_generation_prompt(categories, total)

        raw = self._claude.chat(
            prompt=prompt,
            system=system,
            max_tokens=config.CLAUDE_MAX_TOKENS,
        )

        posts = self._parse_posts(raw, expected=total)
        return posts

    def _build_system_prompt(self) -> str:
        profile = self._profile
        tone    = profile.get("tone", {})
        values  = profile.get("values", [])
        patterns = profile.get("winning_patterns", [])
        constraints = profile.get("constraints", [
            "140文字以内に必ず収める",
            "ハッシュタグは使わない",
        ])

        tone_chars = "\n".join(f"- {c}" for c in tone.get("characteristics", []))
        value_list = "\n".join(f"- {v}" for v in values)
        pattern_list = "\n".join(
            f"- {p['name']}: {p.get('description', '')}"
            for p in patterns
        )
        constraint_list = "\n".join(f"- {c}" for c in constraints)

        return f"""あなたは以下のXアカウントの投稿を代筆するライターです。
このアカウントの口調・価値観・文体を完全に再現してください。

## アカウントのテーマ
{profile.get('theme', 'AI・ビジネス・自動化')}

## 口調・文体の特徴
{tone_chars}

## 繰り返す価値観
{value_list}

## 伸びた投稿パターン
{pattern_list}

## 投稿生成の制約
{constraint_list}

重要: AIっぽい無個性な文章は絶対に書かないでください。
このアカウントの「人間らしさ」と「個性」を最優先にしてください。"""

    def _build_generation_prompt(self, categories: list[str], total: int) -> str:
        cat_labels = {
            "howto":       "ノウハウ・Tips",
            "provocation": "煽り・問題提起",
            "result":      "実績・証拠",
            "tool":        "ツール紹介",
            "mindset":     "マインドセット",
        }

        numbered = "\n".join(
            f"{i+1}. [{cat_labels.get(c, c)}]"
            for i, c in enumerate(categories)
        )

        achievements = self._profile.get("achievements", [])
        ach_note = (
            "\n使える実績: " + "、".join(achievements)
            if achievements else ""
        )

        return f"""以下の{total}件の投稿を生成してください。
各投稿は必ず140文字以内で完結させてください。{ach_note}

{numbered}

出力形式（必ずこの形式で番号付きで出力してください）:
1. 投稿文（140文字以内）
2. 投稿文（140文字以内）
...{total}. 投稿文（140文字以内）

番号と投稿文だけを出力してください。説明や見出しは不要です。"""

    # ── レスポンスパース ──────────────────────────────────

    def _parse_posts(self, raw: str, expected: int) -> list[str]:
        """Claude の応答から投稿文リストを抽出する。"""
        lines = raw.strip().split("\n")
        posts = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # "1. テキスト" 形式を抽出
            m = re.match(r"^\d+\.\s+(.+)$", line)
            if m:
                text = m.group(1).strip()
                if len(text) >= config.POST_MIN_CHARS:
                    posts.append(text[:config.POST_MAX_CHARS])
                else:
                    logger.warning("短すぎる投稿文をスキップ (%d文字): %s", len(text), text)

        if len(posts) < expected:
            logger.warning("期待%d件に対し%d件しか生成されませんでした", expected, len(posts))

        return posts

    # ── レコード構築 ──────────────────────────────────────

    def _build_post_records(
        self,
        texts: list[str],
        categories: list[str],
        start: datetime,
        days: int,
    ) -> list[dict]:
        """投稿テキストにスケジュール情報を付与する。"""
        slots   = config.POST_SCHEDULE
        records = []
        idx     = 0

        for day in range(days):
            post_date = start + timedelta(days=day)
            for slot_num, slot_time in enumerate(slots, 1):
                if idx >= len(texts):
                    break
                hour, minute = map(int, slot_time.split(":"))
                scheduled_at = post_date.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                records.append({
                    "text":         texts[idx],
                    "category":     categories[idx] if idx < len(categories) else "howto",
                    "scheduled_at": scheduled_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "day_index":    day + 1,
                    "slot_index":   slot_num,
                })
                idx += 1

        return records

    # ── プレビュー出力 ────────────────────────────────────

    def _print_preview(self, posts: list[dict]):
        """生成された投稿の一覧を見やすく表示する。"""
        cat_labels = {
            "howto":       "ノウハウ・Tips",
            "provocation": "煽り・問題提起",
            "result":      "実績・証拠",
            "tool":        "ツール紹介",
            "mindset":     "マインドセット",
        }
        print("\n" + "="*60)
        print(f"  生成完了: {len(posts)}件の投稿")
        print("="*60)

        current_day = None
        for i, p in enumerate(posts, 1):
            day = p["day_index"]
            if day != current_day:
                current_day = day
                print(f"\n【Day {day}】")
            slot = p["slot_index"]
            cat  = cat_labels.get(p["category"], p["category"])
            time = p["scheduled_at"].split(" ")[1][:5]
            text_preview = p["text"][:50] + ("…" if len(p["text"]) > 50 else "")
            print(f"  {i:2d}. {time} / {cat} ({len(p['text'])}文字)")
            print(f"      {text_preview}")

        print("="*60 + "\n")
