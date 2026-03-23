"""
agents/post_scheduler.py  ── 投稿スケジューラーエージェント
=============================================================
役割:
  PostQueue を監視し、スケジュール時刻になったら
  TwitterClient を使って X に投稿する。

責任範囲:
  ✅ スケジュール時刻の監視 (ポーリングループ)
  ✅ due な投稿の X への送信
  ✅ 投稿結果の PostQueue への書き戻し
  ✅ シングル投稿（テスト投稿）のサポート
  ❌ 投稿文の生成 (PostGeneratorAgent の責務)
  ❌ キューの補充判断 (ReplenishmentAgent の責務)
"""

import logging
import time
from datetime import datetime
from typing import Optional

from core.twitter_client import TwitterClient
from core.post_queue import PostQueue, STATUS_POSTED, STATUS_FAILED
import config

logger = logging.getLogger(__name__)


class PostSchedulerAgent:
    """
    キューを監視し、スケジュール通りに X へ投稿するエージェント。
    単独で動作し、ReplenishmentAgent・RecoveryAgent と連携する。
    """

    def __init__(
        self,
        queue: Optional[PostQueue] = None,
        twitter: Optional[TwitterClient] = None,
        poll_interval: int = 30,
    ):
        self._queue          = queue   or PostQueue()
        self._twitter        = twitter or TwitterClient()
        self._poll_interval  = poll_interval   # 秒（スケジュール確認間隔）
        self._running        = False

    # ── パブリックAPI ─────────────────────────────────────

    def post_one(self, post_id: Optional[int] = None) -> dict:
        """
        キューから1件取り出して今すぐ投稿する（テスト用）。

        Args:
            post_id: 指定する場合はこのIDの投稿のみを投稿
                     省略時は最初の pending 投稿

        Returns:
            {"ok": bool, "tweet_id": str, "text": str, "error": str}
        """
        target = (
            self._queue.get_post_by_id(post_id) if post_id
            else self._queue.get_next_pending()
        )

        if not target:
            msg = "キューが空です。'python main.py generate' で投稿を生成してください。"
            logger.warning(msg)
            return {"ok": False, "tweet_id": "", "text": "", "error": msg}

        return self._post_record(target)

    def post_record(self, post: dict) -> dict:
        """
        キューのレコード dict を受け取り即時投稿する（RecoveryAgent などから利用）。
        post_one() との違いは「キュー検索をしない」点。
        """
        return self._post_record(post)

    def run_once(self) -> list[dict]:
        """
        現時刻に due な投稿を全件処理して返す。
        自動化ループから呼び出す場合はこちら。
        """
        due = self._queue.get_due_posts()
        if not due:
            return []

        logger.info("%d件の due 投稿を処理します", len(due))
        results = []
        for post in due:
            result = self._post_record(post)
            results.append(result)
            if result["ok"]:
                # 連続投稿のレート制限を避けるため少し待つ
                time.sleep(2)
        return results

    def start_loop(
        self,
        on_replenish_check: Optional[callable] = None,
        on_recovery_check: Optional[callable] = None,
    ):
        """
        スケジュールポーリングループを開始する（ブロッキング）。

        Args:
            on_replenish_check: ReplenishmentAgent のチェック関数
            on_recovery_check:  RecoveryAgent のチェック関数
        """
        self._running = True
        logger.info("スケジューラーループ開始 (ポーリング間隔: %ds)", self._poll_interval)

        while self._running:
            try:
                # 1. リカバリチェック（WiFi復帰後の未投稿処理）
                if on_recovery_check:
                    on_recovery_check()

                # 2. due な投稿を処理
                results = self.run_once()
                if results:
                    ok_count   = sum(1 for r in results if r["ok"])
                    fail_count = len(results) - ok_count
                    logger.info("投稿処理完了: 成功%d件 / 失敗%d件", ok_count, fail_count)

                # 3. 補充チェック
                if on_replenish_check:
                    on_replenish_check()

            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt を受信。ループを停止します。")
                self._running = False
                break
            except Exception as e:
                logger.error("ポーリングループでエラー: %s", e, exc_info=True)

            time.sleep(self._poll_interval)

    def stop(self):
        """ループを停止する。"""
        self._running = False

    # ── 内部メソッド ──────────────────────────────────────

    def _post_record(self, post: dict) -> dict:
        """1件の投稿を X に送り、キューを更新する。"""
        text    = post["text"]
        post_id = post["id"]

        logger.info(
            "投稿中: ID=%d [%s] %s…",
            post_id,
            post.get("category", ""),
            text[:40],
        )

        result = self._twitter.post_tweet(text)

        if result["ok"]:
            self._queue.mark_posted(post_id=post_id, tweet_id=result["tweet_id"])
            logger.info("投稿成功 [%s] tweet_id=%s %s…",
                        post.get("category", ""), result["tweet_id"], text[:60])
        else:
            self._queue.mark_failed(post_id=post_id, error_msg=result["error"])
            logger.error("投稿失敗 ID=%d: %s", post_id, result["error"])

        return {
            "ok":       result["ok"],
            "tweet_id": result.get("tweet_id", ""),
            "text":     text,
            "error":    result.get("error", ""),
            "post_id":  post_id,
        }
