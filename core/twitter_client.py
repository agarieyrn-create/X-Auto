"""
core/twitter_client.py
=======================
X (Twitter) API v2 クライアント
- OAuth 1.0a User Context で認証
- 投稿・削除・認証確認のみを担当
- リトライ・レート制限処理を内包
"""

import time
import logging
from typing import Optional

import tweepy

import config

logger = logging.getLogger(__name__)


class TwitterClient:
    """X API v2 ラッパー。投稿に必要な操作だけを提供します。"""

    def __init__(self):
        auth = tweepy.OAuth1UserHandler(
            consumer_key=config.X_API_KEY,
            consumer_secret=config.X_API_KEY_SECRET,
            access_token=config.X_ACCESS_TOKEN,
            access_token_secret=config.X_ACCESS_TOKEN_SECRET,
        )
        self._api = tweepy.API(auth, wait_on_rate_limit=True)
        self._client = tweepy.Client(
            consumer_key=config.X_API_KEY,
            consumer_secret=config.X_API_KEY_SECRET,
            access_token=config.X_ACCESS_TOKEN,
            access_token_secret=config.X_ACCESS_TOKEN_SECRET,
            wait_on_rate_limit=True,
        )

    # ── 認証確認 ─────────────────────────────────────────

    def verify_credentials(self) -> dict:
        """
        認証が有効かどうかを確認する。
        Returns: {"ok": bool, "screen_name": str, "error": str}
        """
        try:
            user = self._client.get_me()
            screen_name = user.data.username if user and user.data else "unknown"
            logger.info("認証成功: @%s", screen_name)
            return {"ok": True, "screen_name": screen_name, "error": ""}
        except tweepy.errors.Unauthorized as e:
            logger.error("認証失敗 (Unauthorized): %s", e)
            return {"ok": False, "screen_name": "", "error": str(e)}
        except Exception as e:
            logger.error("認証確認中にエラー: %s", e)
            return {"ok": False, "screen_name": "", "error": str(e)}

    # ── 投稿 ──────────────────────────────────────────────

    def post_tweet(self, text: str, retry: int = 3) -> dict:
        """
        ツイートを投稿する。
        DRY_RUN=true の場合は実際には投稿しない。

        Args:
            text: 投稿文 (140文字以内)
            retry: リトライ回数

        Returns:
            {"ok": bool, "tweet_id": str, "error": str}
        """
        if len(text) > config.POST_MAX_CHARS:
            logger.warning("投稿文が%d文字を超えています (%d文字)。切り捨てます。",
                           config.POST_MAX_CHARS, len(text))
            text = text[:config.POST_MAX_CHARS]

        if config.DRY_RUN:
            logger.info("[DRY RUN] 投稿スキップ: %s", text[:50])
            return {"ok": True, "tweet_id": "dry-run-0000", "error": ""}

        for attempt in range(1, retry + 1):
            try:
                response = self._client.create_tweet(text=text)
                tweet_id = str(response.data["id"])
                logger.info("投稿成功 tweet_id=%s", tweet_id)
                return {"ok": True, "tweet_id": tweet_id, "error": ""}

            except tweepy.errors.TooManyRequests:
                wait = 2 ** attempt
                logger.warning("レート制限に達しました。%d秒後にリトライ (%d/%d)",
                               wait, attempt, retry)
                time.sleep(wait)

            except tweepy.errors.Forbidden as e:
                logger.error("投稿が拒否されました (403 Forbidden): %s", e)
                return {"ok": False, "tweet_id": "", "error": f"Forbidden: {e}"}

            except tweepy.errors.HTTPException as e:
                if "402" in str(e):
                    logger.error("クレジット残高が不足しています (402)。"
                                 "Developer Console でチャージしてください。")
                    return {"ok": False, "tweet_id": "",
                            "error": "402 Payment Required - クレジットをチャージしてください"}
                wait = 2 ** attempt
                logger.warning("HTTP エラー (%s)。%d秒後にリトライ (%d/%d)",
                               e, wait, attempt, retry)
                time.sleep(wait)

            except Exception as e:
                logger.error("予期しないエラー: %s", e)
                return {"ok": False, "tweet_id": "", "error": str(e)}

        return {"ok": False, "tweet_id": "", "error": f"{retry}回リトライしましたが失敗しました"}

    # ── 削除 ──────────────────────────────────────────────

    def delete_tweet(self, tweet_id: str) -> bool:
        """ツイートを削除する。DRY_RUN 時はスキップ。"""
        if config.DRY_RUN:
            logger.info("[DRY RUN] 削除スキップ: %s", tweet_id)
            return True
        try:
            self._client.delete_tweet(tweet_id)
            logger.info("削除成功 tweet_id=%s", tweet_id)
            return True
        except Exception as e:
            logger.error("削除失敗 tweet_id=%s: %s", tweet_id, e)
            return False
