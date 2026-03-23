"""
main.py  ── X自動投稿システム エントリーポイント
=================================================
使い方:

  # 環境チェック（APIキー確認）
  python main.py check

  # プロファイル分析（CSVから AI人格を生成）
  python main.py analyze <path/to/analytics.csv>

  # 7日分の投稿を生成してキューに追加
  python main.py generate [--days 7]

  # テスト投稿（1件だけ今すぐ投稿）
  python main.py post-one

  # キュー状況を表示
  python main.py status

  # 完全自動化ループ開始（バックグラウンド常駐）
  python main.py start

各コマンドの詳細は python main.py --help で確認できます。
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# ── ロギング設定 ──────────────────────────────────────────
import config

os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── コマンドハンドラ ──────────────────────────────────────

def cmd_check(args):
    """APIキーと接続を確認する。"""
    print("\n📋 環境チェックを開始します...\n")

    # Anthropic API チェック
    print("1️⃣  Anthropic API キーを確認中...")
    if not config.ANTHROPIC_API_KEY:
        print("   ❌ ANTHROPIC_API_KEY が設定されていません。.env を確認してください。")
    else:
        try:
            from core.claude_client import ClaudeClient
            client = ClaudeClient()
            resp = client.chat("Ping", max_tokens=5)
            print(f"   ✅ Anthropic API: 接続成功")
        except Exception as e:
            print(f"   ❌ Anthropic API エラー: {e}")

    # X API チェック
    print("2️⃣  X API キーを確認中...")
    if not all([
        config.X_API_KEY,
        config.X_API_KEY_SECRET,
        config.X_ACCESS_TOKEN,
        config.X_ACCESS_TOKEN_SECRET,
    ]):
        print("   ❌ X API キーが不完全です。.env を確認してください。")
    else:
        try:
            from core.twitter_client import TwitterClient
            twitter = TwitterClient()
            result = twitter.verify_credentials()
            if result["ok"]:
                print(f"   ✅ X API: 認証成功 (@{result['screen_name']})")
            else:
                print(f"   ❌ X API 認証失敗: {result['error']}")
        except Exception as e:
            print(f"   ❌ X API エラー: {e}")

    # プロファイルチェック
    print("3️⃣  AI人格プロファイルを確認中...")
    if Path(config.PROFILE_PATH).exists():
        print(f"   ✅ プロファイルが見つかりました: {config.PROFILE_PATH}")
    else:
        print(f"   ⚠️  プロファイルがありません。'python main.py analyze <csv>' で生成してください。")

    # キューチェック
    print("4️⃣  投稿キューを確認中...")
    from core.post_queue import PostQueue
    queue = PostQueue()
    summary = queue.get_posts_summary()
    print(f"   📊 キュー: pending={summary.get('pending',0)} "
          f"posted={summary.get('posted',0)} failed={summary.get('failed',0)}")

    print("\n✅ チェック完了\n")


def cmd_analyze(args):
    """CSVからAI人格プロファイルを生成する。"""
    csv_path = args.csv_path
    if not Path(csv_path).exists():
        print(f"❌ CSVファイルが見つかりません: {csv_path}")
        sys.exit(1)

    print(f"\n🔍 プロファイル分析を開始します: {csv_path}\n")

    from agents.profile_analyzer import ProfileAnalyzerAgent
    agent = ProfileAnalyzerAgent()
    profile = agent.analyze_csv(csv_path, output_path=config.PROFILE_PATH)

    print(f"\n✅ AI人格プロファイルを生成しました: {config.PROFILE_PATH}")
    print(f"   テーマ: {profile.get('theme', '')}")
    print(f"   価値観: {len(profile.get('values', []))}個")
    print(f"   伸びたパターン: {len(profile.get('winning_patterns', []))}個\n")
    print("次のステップ: python main.py generate")


def cmd_generate(args):
    """指定日数分の投稿を生成する。"""
    days = args.days
    print(f"\n🤖 {days}日分の投稿を生成中...\n")

    from core.post_queue import PostQueue
    from agents.post_generator import PostGeneratorAgent

    queue  = PostQueue()
    agent  = PostGeneratorAgent(queue=queue)
    posts  = agent.generate_bulk(days=days)

    print(f"\n✅ {len(posts)}件の投稿を生成してキューに追加しました。")
    print("次のステップ: python main.py post-one  (テスト投稿)")
    print("             python main.py start      (完全自動化ループ)")


def cmd_post_one(args):
    """テスト投稿（1件だけ今すぐ投稿）。"""
    print("\n🚀 テスト投稿を実行します...\n")

    from core.post_queue import PostQueue
    from core.twitter_client import TwitterClient
    from agents.post_scheduler import PostSchedulerAgent

    queue     = PostQueue()
    twitter   = TwitterClient()
    scheduler = PostSchedulerAgent(queue=queue, twitter=twitter)
    result    = scheduler.post_one()

    if result["ok"]:
        print(f"\n✅ 投稿成功！")
        print(f"   ツイートID: {result['tweet_id']}")
        print(f"   内容: {result['text'][:80]}")
    else:
        print(f"\n❌ 投稿失敗: {result['error']}")
        sys.exit(1)


def cmd_status(args):
    """キューの状況を表示する。"""
    from core.post_queue import PostQueue

    queue   = PostQueue()
    summary = queue.get_posts_summary()
    pending = queue.get_all_pending()

    print("\n📊 キュー状況")
    print(f"  pending (未投稿): {summary.get('pending', 0)}件")
    print(f"  posted  (投稿済): {summary.get('posted', 0)}件")
    print(f"  failed  (失敗  ): {summary.get('failed', 0)}件")

    if pending:
        print(f"\n📋 次の投稿予定 (最大5件):")
        for p in pending[:5]:
            sched = p.get("scheduled_at", "未スケジュール")
            print(f"  [{sched}] {p['text'][:60]}…")

    print()


def cmd_start(args):
    """完全自動化ループを開始する。"""
    print("\n🔄 X自動投稿システムを起動します...\n")
    print("  Ctrl+C で停止できます\n")

    from core.post_queue import PostQueue
    from core.twitter_client import TwitterClient
    from agents.post_scheduler import PostSchedulerAgent
    from agents.replenishment_agent import ReplenishmentAgent
    from agents.recovery_agent import RecoveryAgent
    from agents.post_generator import PostGeneratorAgent

    queue     = PostQueue()
    twitter   = TwitterClient()
    generator = PostGeneratorAgent(queue=queue)
    scheduler = PostSchedulerAgent(queue=queue, twitter=twitter)
    replenish = ReplenishmentAgent(queue=queue, generator=generator)
    recovery  = RecoveryAgent(queue=queue, scheduler=scheduler)

    # キューが空なら初期生成
    summary = queue.get_posts_summary()
    if summary.get("pending", 0) == 0:
        print("キューが空です。初期投稿を生成します...")
        generator.generate_bulk(days=config.REPLENISH_DAYS)

    # ループ開始
    scheduler.start_loop(
        on_replenish_check=replenish.check_and_replenish,
        on_recovery_check=recovery.check_and_recover,
    )


# ── CLI 定義 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="X自動投稿システム",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check
    subparsers.add_parser("check", help="APIキーと接続を確認する")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="CSVからAI人格プロファイルを生成")
    p_analyze.add_argument("csv_path", help="XアナリティクスのCSVファイルパス")

    # generate
    p_gen = subparsers.add_parser("generate", help="投稿を生成してキューに追加")
    p_gen.add_argument("--days", type=int, default=config.REPLENISH_DAYS,
                       help=f"生成する日数 (デフォルト: {config.REPLENISH_DAYS})")

    # post-one
    subparsers.add_parser("post-one", help="テスト投稿（1件だけ今すぐ投稿）")

    # status
    subparsers.add_parser("status", help="キューの状況を表示")

    # start
    subparsers.add_parser("start", help="完全自動化ループを開始")

    args = parser.parse_args()

    commands = {
        "check":    cmd_check,
        "analyze":  cmd_analyze,
        "generate": cmd_generate,
        "post-one": cmd_post_one,
        "status":   cmd_status,
        "start":    cmd_start,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
