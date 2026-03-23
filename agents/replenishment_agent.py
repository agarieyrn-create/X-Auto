"""
agents/replenishment_agent.py  ── 補充エージェント
=====================================================
役割:
  PostQueue の残件数を監視し、閾値を下回ったら
  PostGeneratorAgent を呼び出して自動的に追加生成する。

責任範囲:
  ✅ キュー残件数の監視
  ✅ 補充トリガーの判定
  ✅ PostGeneratorAgent への委譲
  ✅ 補充サイクルのログ記録
  ❌ 投稿文の生成ロジック (PostGeneratorAgent の責務)
  ❌ 投稿の実行 (PostSchedulerAgent の責務)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from core.post_queue import PostQueue
import config

logger = logging.getLogger(__name__)


class ReplenishmentAgent:
    """
    キューが枯渇しないように自動補充するエージェント。
    PostSchedulerAgent のポーリングループから呼び出される。
    """

    def __init__(
        self,
        queue: Optional[PostQueue] = None,
        generator=None,              # PostGeneratorAgent (循環import回避のため型ヒントなし)
        threshold: int = config.REPLENISH_THRESHOLD,
        replenish_days: int = config.REPLENISH_DAYS,
    ):
        self._queue          = queue or PostQueue()
        self._generator      = generator
        self._threshold      = threshold
        self._replenish_days = replenish_days
        self._last_check     = datetime.min

    # ── パブリックAPI ─────────────────────────────────────

    def check_and_replenish(self) -> bool:
        """
        キューをチェックし、必要なら補充する。
        スケジューラーのポーリングループから呼ばれる。

        Returns:
            True: 補充を実行した
            False: 補充は不要だった
        """
        now = datetime.now()

        # 頻繁すぎるチェックを避ける（最低1時間間隔）
        if (now - self._last_check).total_seconds() < 3600:
            return False
        self._last_check = now

        pending_count = self._queue.get_pending_count()
        logger.debug("キュー残件数: %d件 (閾値: %d件)", pending_count, self._threshold)

        if pending_count > self._threshold:
            return False

        logger.info(
            "キューが閾値以下になりました (%d件 <= %d件)。補充を開始します。",
            pending_count,
            self._threshold,
        )

        self._replenish()
        return True

    def force_replenish(self, days: Optional[int] = None):
        """強制的に補充を実行する（手動・テスト用）。"""
        _days = days or self._replenish_days
        logger.info("強制補充: %d日分を生成します", _days)
        self._replenish(days=_days)

    # ── 内部メソッド ──────────────────────────────────────

    def _replenish(self, days: Optional[int] = None):
        """PostGeneratorAgent を呼び出して生成・追加する。"""
        if self._generator is None:
            # 遅延インポート（循環参照回避）
            from agents.post_generator import PostGeneratorAgent
            self._generator = PostGeneratorAgent(queue=self._queue)

        _days = days or self._replenish_days

        # 最後のスケジュール済み投稿の翌日から開始
        start_date = self._calc_start_date()

        logger.info("補充生成: %d日分 (開始日: %s)", _days, start_date.date())
        added = self._generator.generate_bulk(days=_days, start_date=start_date)
        logger.info("補充完了: %d件追加", len(added))

        # サマリーを出力
        summary = self._queue.get_posts_summary()
        logger.info(
            "キュー状況: pending=%d posted=%d failed=%d",
            summary.get("pending", 0),
            summary.get("posted", 0),
            summary.get("failed", 0),
        )

    def _calc_start_date(self) -> datetime:
        """
        次の補充を開始する日付を計算する。
        キューに pending がある場合は最後の scheduled_at の翌日。
        ない場合は翌日。
        """
        all_pending = self._queue.get_all_pending()
        if not all_pending:
            return (datetime.now() + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        last_scheduled = max(
            p["scheduled_at"] for p in all_pending if p.get("scheduled_at")
        )
        last_dt = datetime.strptime(last_scheduled, "%Y-%m-%d %H:%M:%S")
        return (last_dt + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
