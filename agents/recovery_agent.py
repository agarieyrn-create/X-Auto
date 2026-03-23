"""
agents/recovery_agent.py  ── リカバリエージェント
====================================================
役割:
  WiFi断絶やサーバー停止などで投稿できなかった場合に、
  復帰後に未投稿分をまとめて投稿するリカバリ処理を担う。

責任範囲:
  ✅ ネットワーク接続の確認
  ✅ 未投稿（missed）ポストの検出
  ✅ RECOVERY_WINDOW 内の missed post の処理
  ✅ リカバリ結果のログ記録
  ❌ 通常のスケジュール投稿 (PostSchedulerAgent の責務)
  ❌ 投稿文の生成 (PostGeneratorAgent の責務)
"""

import logging
import socket
import time
from datetime import datetime, timedelta
from typing import Optional

from core.post_queue import PostQueue
import config

logger = logging.getLogger(__name__)

# ネットワーク疎通確認のホスト
_CHECK_HOST = "8.8.8.8"
_CHECK_PORT = 53
_CHECK_TIMEOUT = 3


class RecoveryAgent:
    """
    未投稿の missed post をリカバリするエージェント。
    PostSchedulerAgent のポーリングループから呼び出される。
    """

    def __init__(
        self,
        queue: Optional[PostQueue] = None,
        scheduler=None,              # PostSchedulerAgent (循環import回避)
        recovery_window_hours: int = config.RECOVERY_WINDOW_HOURS,
    ):
        self._queue                = queue or PostQueue()
        self._scheduler            = scheduler
        self._window_hours         = recovery_window_hours
        self._last_online          = datetime.now()
        self._was_offline          = False

    # ── パブリックAPI ─────────────────────────────────────

    def check_and_recover(self) -> list[dict]:
        """
        接続状態を確認し、オフラインから復帰した場合にリカバリを実行する。
        PostSchedulerAgent のループから呼び出す。

        Returns:
            リカバリした投稿結果リスト
        """
        if not config.RECOVERY_ENABLED:
            return []

        online = self._is_online()

        if online:
            if self._was_offline:
                # オフラインから復帰！
                offline_duration = datetime.now() - self._last_online
                logger.info(
                    "ネットワーク復帰を検出 (オフライン時間: %s)。リカバリを開始します。",
                    offline_duration,
                )
                self._was_offline = False
                return self._recover()
            else:
                self._last_online = datetime.now()
        else:
            if not self._was_offline:
                logger.warning("ネットワーク接続が切断されました。")
                self._was_offline = True

        return []

    def force_recover(self) -> list[dict]:
        """強制的にリカバリを実行する（手動・テスト用）。"""
        logger.info("強制リカバリを実行します")
        return self._recover()

    # ── 内部メソッド ──────────────────────────────────────

    def _is_online(self) -> bool:
        """ネットワーク接続を確認する（グローバルタイムアウトを汚染しない）。"""
        try:
            with socket.create_connection((_CHECK_HOST, _CHECK_PORT), timeout=_CHECK_TIMEOUT):
                pass
            return True
        except (socket.error, OSError):
            return False

    def _recover(self) -> list[dict]:
        """
        RECOVERY_WINDOW 内の missed posts を取得して投稿する。
        """
        if self._scheduler is None:
            from agents.post_scheduler import PostSchedulerAgent
            self._scheduler = PostSchedulerAgent(queue=self._queue)

        now     = datetime.now()
        cutoff  = now - timedelta(hours=self._window_hours)

        # due_posts は scheduled_at <= now のものを返すので、
        # ここでは cutoff 以降のものに絞る
        due_all = self._queue.get_due_posts(now=now)
        missed  = [
            p for p in due_all
            if p.get("scheduled_at") and
               datetime.strptime(p["scheduled_at"], "%Y-%m-%d %H:%M:%S") >= cutoff
        ]

        if not missed:
            logger.info("リカバリ対象の未投稿はありません")
            return []

        logger.info("%d件の未投稿をリカバリします", len(missed))
        results = []
        for post in missed:
            result = self._scheduler.post_record(post)
            results.append(result)
            time.sleep(2)  # レート制限対応

        ok_count   = sum(1 for r in results if r["ok"])
        fail_count = len(results) - ok_count
        logger.info("リカバリ完了: 成功%d件 / 失敗%d件", ok_count, fail_count)
        return results
