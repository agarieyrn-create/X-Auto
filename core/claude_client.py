"""
core/claude_client.py
======================
Anthropic API クライアント
- メッセージ送信・ストリーミングのラッパー
- リトライ・エラーハンドリングを内包
- 各エージェントはこのクライアントを通じて Claude を呼び出す
"""

import time
import logging
from typing import Optional

import anthropic

import config

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Anthropic API の薄いラッパー。エージェントから利用します。"""

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        retry: int = 3,
    ) -> str:
        """
        Claude にメッセージを送り、テキストレスポンスを返す。

        Args:
            prompt:     ユーザーメッセージ
            system:     システムプロンプト
            model:      使用モデル（省略時は config.CLAUDE_MODEL）
            max_tokens: 最大トークン数
            retry:      リトライ回数

        Returns:
            Claude のレスポンステキスト
        """
        _model = model or config.CLAUDE_MODEL
        _max_tokens = max_tokens or config.CLAUDE_MAX_TOKENS

        messages = [{"role": "user", "content": prompt}]
        kwargs = {
            "model": _model,
            "max_tokens": _max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        for attempt in range(1, retry + 1):
            try:
                response = self._client.messages.create(**kwargs)
                if not response.content:
                    raise ValueError("Claude からの応答が空でした（content が空リスト）")
                text = response.content[0].text
                logger.debug("Claude応答 (%d文字): %s…", len(text), text[:80])
                return text

            except anthropic.RateLimitError:
                wait = 2 ** attempt
                logger.warning("レート制限。%d秒後にリトライ (%d/%d)", wait, attempt, retry)
                time.sleep(wait)

            except anthropic.APIStatusError as e:
                logger.error("Anthropic API エラー (%s): %s", e.status_code, e.message)
                if attempt == retry:
                    raise
                time.sleep(2 ** attempt)

            except Exception as e:
                logger.error("予期しないエラー: %s", e)
                if attempt == retry:
                    raise
                time.sleep(2 ** attempt)

        raise RuntimeError(f"Claude API: {retry}回リトライしましたが失敗しました")
