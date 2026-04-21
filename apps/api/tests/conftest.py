"""pytest 全体の共通設定。

リポジトリ root の .env / .env.local を読み込むことで、integration テストが
src.app を import する前でも環境変数にアクセスできるようにする。
"""

from dotenv import find_dotenv, load_dotenv

# src/app.py と同じ順で読む（.env → .env.local で上書き）
load_dotenv(find_dotenv(".env", usecwd=True), override=False)
load_dotenv(find_dotenv(".env.local", usecwd=True), override=True)
