"""
tests/conftest.py
==================
テスト共通のフィクスチャ・設定
"""

import pytest
import config


@pytest.fixture(autouse=True)
def patch_min_chars(monkeypatch):
    """テスト時は文字数下限を緩和してモックテキストを通す。"""
    monkeypatch.setattr(config, "POST_MIN_CHARS", 5)
