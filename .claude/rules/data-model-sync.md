---
paths:
  - "docs/data-model.md"
  - "packages/shared-types/src/**"
  - "apps/api/src/schemas/**"
  - "apps/api/tests/test_schema_parity.py"
---

# Data Model Sync Rules

Routeful のデータモデルは **docs/data-model.md / packages/shared-types / apps/api/src/schemas の 3 箇所に分散**している。このどれかを変えるときは、残り 2 つも必ず同じトランザクションで更新し、クロスチェックテストを通すこと。

## 正典の順序

`docs/data-model.md` が唯一の正典。コード側（TS / Python）はどちらもここのミラー。

## 変更フロー（省略不可）

```
1. docs/data-model.md を更新
   └─ DDL セクション / TypeScript 型定義セクションの両方を編集
2. packages/shared-types/src/index.ts を同期
   └─ 追加型、変更されたフィールド、削除フィールドを反映
3. apps/api/src/schemas/__init__.py を同期
   └─ Pydantic v2 の StrictStr / Literal / date / datetime を TS と揃える
   └─ 未知フィールド拒否のため _StrictBase を継承
4. apps/api/tests/test_schema_parity.py の EXPECTED_FIELDS を同期
   └─ 新規エンティティは _MODELS dict にも登録
5. pnpm test で 38+件が全 PASS することを確認
   └─ test_schema_parity が落ちたら片側しか更新していない
```

## Do NOT

- **片側だけ変更してコミットするな**。TS と Pydantic と docs の 3 点セットが原則
- **`_StrictBase` の `extra="forbid"` を外すな**。未知フィールドを許すと TS 側の Omit などに対応していない構造が混入する
- **`EXPECTED_FIELDS` を Pydantic に合わせて書き換えるな**。TS が変わって Pydantic がまだ追従していない段階で `EXPECTED_FIELDS` を Pydantic 現状に合わせると、ドリフト検出が無効化される。正しい手順は「TS → Pydantic → EXPECTED_FIELDS」の順
- **Pydantic の datetime を str で書くな**。TS の `string`（ISO 形式）は Pydantic では `datetime` 型で表現し、`.model_dump(mode="json")` で ISO 文字列にシリアライズされる
- **`model_json_schema()` を生成物としてコミットするな**。毎回動的に生成される。固定ファイルとして保存するなら別途 build ステップを検討

## クロスチェックの仕組み

`apps/api/tests/test_schema_parity.py` の `EXPECTED_FIELDS` は TS 側の真実を Python 側にハードコードしたもの。

- TS → 変更があれば `EXPECTED_FIELDS` と Pydantic の両方を更新
- Pydantic → 変更があれば `EXPECTED_FIELDS` と TS の両方を更新
- `EXPECTED_FIELDS` だけ更新 → Pydantic と比較して落ちる

双方向のドリフト検出を Python 側の pytest 1 個で担保している。TS 側の静的チェック（tsc）は compile 時に型の整合性を担保するので別枠。

## Optional フィールドの扱い

| TS 表記 | Pydantic 表記 | JSON 表現 |
|---|---|---|
| `foo?: string` | `foo: str \| None = None` | `{"foo": null}` または省略（exclude_none 次第） |
| `foo: string \| null` | `foo: str \| None` | 常に `"foo"` キー含む、値は null 可 |

API レスポンスでは原則 `exclude_none` を使わず、null を明示する方針（フロントのデフォルト値処理を簡単にするため）。

## 変更例

### 例: Plan に `memo: string | null` を追加

1. `docs/data-model.md` の DDL に `memo TEXT` を追加、TS 型定義にも `memo: string | null` を追加
2. `packages/shared-types/src/index.ts` の `Plan` に `memo: string | null` を追加
3. `apps/api/src/schemas/__init__.py` の `Plan` に `memo: str | None` を追加
4. `apps/api/tests/test_schema_parity.py` の `EXPECTED_FIELDS["Plan"]` に `"memo"` を追加
5. Supabase 側で `ALTER TABLE plans ADD COLUMN memo TEXT;`（ダッシュボードで実行）
6. `pnpm test` 確認

この流れを破ると、デプロイ後にフロントが「memo フィールドが undefined」でクラッシュする、または Pydantic のバリデーションが API リクエストを拒否するなど、発見が遅い事故を起こす。
