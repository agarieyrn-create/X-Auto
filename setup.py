"""
setup.py  ── セットアップスクリプト
======================================
Claude Codeから呼び出されるセットアップ手順。
このファイルを実行すると、.envファイルの作成と
依存関係のインストールを対話的に完了できる。

使い方:
  python setup.py
"""

import os
import subprocess
import sys
from pathlib import Path


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {cmd}")
    return subprocess.run(cmd, shell=True, check=check)


def ask(prompt: str, default: str = "") -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    return val if val else default


def main():
    print("\n" + "=" * 60)
    print("  X自動投稿システム セットアップ")
    print("=" * 60 + "\n")

    # ── 1. Python バージョン確認 ─────────────────────────
    print("📋 Step 1/4: Python バージョン確認")
    major, minor = sys.version_info[:2]
    print(f"  Python {major}.{minor} が見つかりました")
    if (major, minor) < (3, 10):
        print(f"  ❌ Python 3.10以上が必要です（現在: {major}.{minor}）")
        sys.exit(1)
    print("  ✅ バージョン OK\n")

    # ── 2. 依存パッケージインストール ───────────────────
    print("📦 Step 2/4: 依存パッケージをインストール")
    run(f"{sys.executable} -m pip install -r requirements.txt --quiet")
    print("  ✅ インストール完了\n")

    # ── 3. .env ファイル作成 ─────────────────────────────
    print("🔑 Step 3/4: APIキーの設定")
    env_path = Path(".env")

    if env_path.exists():
        overwrite = input("  .env がすでに存在します。上書きしますか？ [y/N]: ").strip().lower()
        if overwrite != "y":
            print("  スキップしました\n")
        else:
            _write_env(env_path)
    else:
        _write_env(env_path)

    # ── 4. ディレクトリ作成 ──────────────────────────────
    print("📁 Step 4/4: ディレクトリを作成")
    for d in ["data", "logs"]:
        Path(d).mkdir(exist_ok=True)
        print(f"  ✅ {d}/ を作成しました")

    # ── 完了 ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ✅ セットアップ完了！")
    print("=" * 60)
    print("""
次のステップ:
  1. 接続確認:
     python main.py check

  2. プロファイル生成（XアナリティクスのCSVが必要）:
     python main.py analyze path/to/analytics.csv

  3. 7日分の投稿生成:
     python main.py generate

  4. テスト投稿（1件）:
     python main.py post-one

  5. 完全自動化ループ開始:
     python main.py start
""")


def _write_env(env_path: Path):
    print()
    print("  以下のAPIキーを入力してください。")
    print("  (入力中は文字が表示されます。後で .env を直接編集することもできます)\n")

    import getpass

    x_api_key             = getpass.getpass("  X API Key             : ")
    x_api_key_secret      = getpass.getpass("  X API Key Secret      : ")
    x_access_token        = getpass.getpass("  X Access Token        : ")
    x_access_token_secret = getpass.getpass("  X Access Token Secret : ")
    anthropic_api_key     = getpass.getpass("  Anthropic API Key     : ")

    dry_run = input("\n  DRY_RUN モードにしますか？（実際には投稿されません）[y/N]: ").strip().lower()
    dry_run_val = "true" if dry_run == "y" else "false"

    env_content = f"""# X (Twitter) API
X_API_KEY={x_api_key}
X_API_KEY_SECRET={x_api_key_secret}
X_ACCESS_TOKEN={x_access_token}
X_ACCESS_TOKEN_SECRET={x_access_token_secret}

# Anthropic API
ANTHROPIC_API_KEY={anthropic_api_key}

# 動作設定
DRY_RUN={dry_run_val}
LOG_LEVEL=INFO
"""
    env_path.write_text(env_content, encoding="utf-8")
    print(f"\n  ✅ .env を作成しました\n")


if __name__ == "__main__":
    main()
