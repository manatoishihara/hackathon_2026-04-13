---
paths:
  - "apps/api/src/**/*.py"
  - "apps/api/tests/**/*.py"
---

# Flask API Rules

## アーキテクチャ

- **Blueprint で機能分割**。単一 `app.py` に全部書くな
  - `apps/api/src/routes/plans.py` — プラン生成・取得・編集
  - `apps/api/src/routes/evidence.py` — Evidence Pack 構築
  - `apps/api/src/routes/health.py` — ヘルスチェック
- **ビジネスロジックは `services/` に分離**。ルート関数は薄く保つ
  - `apps/api/src/services/plan_generator.py`
  - `apps/api/src/services/evidence_builder.py`
- **外部 API 呼び出しは `clients/` に分離**
  - `apps/api/src/clients/openai_client.py`
  - `apps/api/src/clients/google_maps.py`
  - `apps/api/src/clients/rakuten_travel.py`

## Pydantic 必須

- **全ての API 入出力は Pydantic v2 モデルで定義**
- Flask は標準では型検証しない。自前で`@validate_request` デコレータを書け
- 型定義は `apps/api/src/schemas/` に集約し、フロント型と一致させる（`packages/shared-types` と同期）

```python
# apps/api/src/schemas/plan.py
from pydantic import BaseModel, Field
from datetime import datetime

class PlanItem(BaseModel):
    id: str
    type: Literal["activity", "meal", "transit", "lodging"]
    start_time: datetime
    end_time: datetime
    location: Location
    evidence: Evidence
    # ... docs/data-model.md の定義と完全一致させる
```

## 並列 API 呼び出し

**LLM + Places + Routes + 楽天 を逐次で呼ぶな**。合計30秒超で タイムアウト リスク。

```python
# 良い例: 並列化
from concurrent.futures import ThreadPoolExecutor

def build_evidence_pack(query: EvidenceQuery) -> EvidencePack:
    with ThreadPoolExecutor(max_workers=4) as executor:
        places_future = executor.submit(fetch_places, query)
        lodging_future = executor.submit(fetch_lodging, query)
        # ...
    return assemble_pack(places_future.result(), lodging_future.result())
```

非同期を使うなら `Flask[async]` + `httpx.AsyncClient`。ただし Flask の非同期サポートは限定的なので、**`ThreadPoolExecutor` を第一選択**にせよ。

## エラーハンドリング

- RFC 7807 (Problem Details) 形式のエラーレスポンス
- 外部 API エラーを生のまま返すな。プロダクト用語に翻訳
- タイムアウトは必ず設定（Places: 5s、Routes: 5s、OpenAI: 60s）

```python
from werkzeug.exceptions import HTTPException

@app.errorhandler(HTTPException)
def handle_exception(e):
    return {
        "type": f"https://routeful.vercel.app/errors/{e.code}",
        "title": e.name,
        "status": e.code,
        "detail": str(e),
    }, e.code
```

## 環境変数の扱い

- 読み込みは `apps/api/src/config.py` に集約
- `os.getenv("KEY")` を各所に散らすな
- 起動時に必須キーをチェックし、欠けていればエラーで停止

## ロギング

- `print` を使うな。`logging` モジュール
- 外部 API 呼び出しは必ず `INFO` でリクエスト/レスポンスをログ（レスポンスは summary で、個人情報は除外）
- エラーは `ERROR` でスタックトレース込み

## テスト

- `pytest` + `pytest-flask`
- 外部 API は `responses` か `vcrpy` でモック（本番APIを叩くテストを書くな）
- カバレッジ目標: `services/` は 80% 以上、`routes/` は 60% 以上
