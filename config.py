"""
X Auto-Posting System - Configuration
======================================
投稿スケジュール・動作パラメータをすべてここで管理します。
数字を変えるだけで動作が変わります。
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── X (Twitter) API 認証情報 ─────────────────────────────
X_API_KEY             = os.getenv("X_API_KEY", "")
X_API_KEY_SECRET      = os.getenv("X_API_KEY_SECRET", "")
X_ACCESS_TOKEN        = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET", "")

# ─── Anthropic API 認証情報 ───────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ─── Claude モデル設定 ────────────────────────────────────
CLAUDE_MODEL          = "claude-opus-4-6"          # 投稿生成に使うモデル
CLAUDE_PROFILE_MODEL  = "claude-opus-4-6"          # プロファイル分析に使うモデル
CLAUDE_MAX_TOKENS     = 2048

# ─── 投稿スケジュール ─────────────────────────────────────
# 毎日この時間に自動投稿される (HH:MM 形式、24時間)
POST_SCHEDULE = [
    "08:00",
    "12:30",
    "19:00",
]

# ─── 投稿補充設定 ─────────────────────────────────────────
REPLENISH_DAYS        = 7     # 補充する日数
REPLENISH_THRESHOLD   = 7     # キューがこの件数以下になったら補充
POSTS_PER_DAY         = len(POST_SCHEDULE)

# ─── カテゴリ比率 (合計が1.0になるように) ──────────────────
# ここの数字を変えるだけで投稿の内訳が変わります
CATEGORY_RATIO = {
    "howto":       0.35,  # ノウハウ・Tips
    "provocation": 0.25,  # 煽り・問題提起
    "result":      0.20,  # 実績・証拠
    "tool":        0.10,  # ツール紹介
    "mindset":     0.10,  # マインドセット
}

# ─── 投稿文字数 ───────────────────────────────────────────
POST_MAX_CHARS  = 140    # Xの文字数制限
POST_MIN_CHARS  = 80     # これより短い投稿は再生成

# ─── データ保存先 ─────────────────────────────────────────
DB_PATH      = "data/posts.db"
LOG_PATH     = "logs/x_auto.log"
PROFILE_PATH = "account_profile.py"

# ─── リカバリ設定 ─────────────────────────────────────────
# WiFi断絶後の復帰時に未投稿分をまとめて投稿する
RECOVERY_ENABLED       = True
RECOVERY_WINDOW_HOURS  = 24   # この時間内の未投稿分だけリカバリ対象

# ─── デバッグ ─────────────────────────────────────────────
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"  # Trueならxへの実投稿はしない
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
