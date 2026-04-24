# Phase 1.3d + DB-2 + DB-3 実装計画

> **Revision history:**
> - 2026-04-24 v1: 初版
> - 2026-04-24 v2: Codex レビュー反映（競合安全性・compare-and-set + RPC 原子化 / status 方針一本化 / Structured Output strict 要件対応 / ハルシネーション追加検証 / 全体 deadline 短縮 / opening_hours 事前正規化 / pg_cron 冪等化 / Branch 細分割 / integration テスト 3 件化 / PROMPT_VERSION は将来拡張に明記）
> - 2026-04-24 v3: Codex v2 re-review 反映（CAS を RPC 化で race 消去 / SDK 呼出経路を `client.chat.completions.parse` に統一 / opening_hours parse 失敗挙動を "skip validation" に統一 / v1 残留記述削除 / RPC 通信失敗の曖昧ケース仕様化 / openai SDK 最小バージョン固定 / RLS テストを PostgrestAPIError コード検証に強化 / 409 表に generating も明記）

**Goal:** `/api/plans/generate` に LLM 接続を組み込み、Evidence Pack から実在スポットのみを使ってプランを生成する。ハルシネーション（架空の place_id、時刻逆転、予算超過）はサーバー validator で全 reject + 最大 2 回リトライ + `gpt-4o-mini` フォールバック。併せて `plan_items` を Supabase に保存し、`plans.status` を `succeeded` / `failed` に遷移する。並走して DB-2（RLS E2E テスト）と DB-3（pg_cron クリーンアップ）も実装する。

**Architecture:**
```
Client → /api/plans/generate (auth, payload validate, load pack, transit validate, model_copy merged pack)
       ↓
     [Phase 1.3d 追加]
       ↓ plan_id owner 検証（plans.session_id == g.owner_session_id、403 / 404）
       ↓ build_prompt(merged_pack, participants, budget_constraints, temporal_constraints)
       ↓ generator.generate_plan(prompt, model=gpt-4o, retry=2)
       │   ├ OpenAI Structured Output（response_format=json_schema、strict=True）
       │   ├ validator.validate_llm_output(llm_items, merged_pack)
       │   │   ├ place_id 所属 / 時刻順序 / 営業時間 best-effort / transit 整合 / 予算 / 時系列重複
       │   │   └ 失敗 → 同エラー内容を user prompt に再注入してリトライ
       │   └ 3 回失敗 → gpt-4o-mini にフォールバックして 1 回だけ追加試行
       ↓
     bulk INSERT plan_items + UPDATE plans.status = 'succeeded' (失敗時は 'failed')
       ↓
     Response: { "plan_id": <UUID> }  ← 1.3c の `{ "plan_id": null }` を置換
```

**Tech Stack:** OpenAI SDK 1.x (`response_format={"type": "json_schema", "schema": ..., "strict": True}`) / pytest-mock / responses（外部 API）/ Supabase Python client / pg_cron (Supabase 組込)

**Branches（v2 で 5 段階に再分割、Codex Should-fix #10）:**
0. `feat/opening-hours-normalization` — Branch 0: `PlacePoint.opening_hours` を構造化（`list[OpeningHoursSlot]`）+ evidence builder 側の parser 実装。evidence-pack.md 正典（`"09:00-18:00"`）と pack.py 実装（weekdayDescriptions）の乖離を解消
1. `feat/llm-prompt-and-validator` — Branch A: prompt builder + LLM 出力 validator（OpenAI 未接続、純関数、8 項目 + transit 詳細検証）
2. `feat/llm-generator-atomic` — Branch B: OpenAI generator + リトライ/フォールバック + **atomic plan finalize RPC**（Postgres 関数で plan_items bulk INSERT + plans.status UPDATE を 1 トランザクション）
3. `feat/plans-generate-route` — Branch C: `/api/plans/generate` 最終配線（compare-and-set ロック + LLM 呼び出し + RPC 保存）+ debug mode 廃止
4. `feat/db-integrity-sweep` — Branch D: DB-2 RLS E2E テスト + DB-3 pg_cron クリーンアップ SQL（冪等化、Branch 0 依存なし、並行可）

前提: 1.3c + `PlanGenerationPayload.plan_id` + frontend-skeleton 全て develop マージ済み ✅

---

## 方針 / 判断確定（v2 改訂）

### 競合安全性 — v3 再確定（Codex Must-fix #4-5、v2 re-review 指摘）

二重 generate / 中断後再試行 / 同一 plan_id への同時書き込みを防ぐため、**compare-and-set を Postgres RPC に閉じ込めて race を消し、原子保存も別 RPC** で実装する。v2 では Flask 側で UPDATE RETURNING + 補足 SELECT する構成だったが、race で「lock 取れなかった瞬間に別プロセスが failed に遷移 → 補足 SELECT で failed を拾って 500」という穴があった。v3 ではこれを RPC 内で完結させる。

**lock 取得 RPC**:

```sql
-- 冪等化: enum は IF NOT EXISTS 的扱いができないので DO ブロックで存在チェック
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'plan_lock_result') THEN
    CREATE TYPE plan_lock_result AS ENUM ('acquired', 'not_found', 'already_generating', 'already_succeeded');
  END IF;
END $$;

CREATE OR REPLACE FUNCTION acquire_plan_generation_lock(
  p_plan_id UUID,
  p_session_id UUID
) RETURNS plan_lock_result
LANGUAGE plpgsql
AS $$
DECLARE
  v_status TEXT;
  v_updated INTEGER;
BEGIN
  -- 対象 plan をロック（FOR UPDATE）、存在 + owner 一致を同時検証。複数接続が同時に来ても
  -- 先頭の 1 つだけが status を読み、残りはそれを待つ。RPC 内なので Flask 側の race は発生しない。
  SELECT status INTO v_status
  FROM plans
  WHERE id = p_plan_id AND session_id = p_session_id
  FOR UPDATE;

  IF NOT FOUND THEN
    -- plan_id 未知 or owner 不一致（漏えい防止でどちらも not_found）
    RETURN 'not_found';
  END IF;

  IF v_status IN ('draft', 'failed') THEN
    UPDATE plans SET status = 'generating', updated_at = NOW() WHERE id = p_plan_id;
    RETURN 'acquired';
  ELSIF v_status = 'generating' THEN
    RETURN 'already_generating';
  ELSIF v_status = 'succeeded' THEN
    RETURN 'already_succeeded';
  ELSE
    -- 想定外 status（将来のマイグレーション不整合など）
    RAISE EXCEPTION 'unexpected plan status: %', v_status;
  END IF;
END;
$$;
```

**mark_failed RPC**:

```sql
CREATE OR REPLACE FUNCTION mark_plan_failed(
  p_plan_id UUID,
  p_session_id UUID
) RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
  -- compare-and-set: generating のときだけ failed に遷移。別プロセスが succeeded に到達してれば no-op
  UPDATE plans
  SET status = 'failed', updated_at = NOW()
  WHERE id = p_plan_id AND session_id = p_session_id AND status = 'generating';
END;
$$;
```

**注**: 既存の「generating stuck cleanup（DB-3）」で 1 時間超の generating は削除されるため、長期 stuck による永続ロックは発生しない。

**`updated_at = NOW()` の扱い** (v2 の `"NOW()"` 文字列が危険との指摘への対応): 上のように **SQL 内で直接 `NOW()` を書く** ことで、PostgreSQL 側で評価される。Python 側は RPC を呼ぶだけで、更新対象カラムには触れない。

**原子保存の RPC（Postgres 関数）**:

```sql
-- plan_items の bulk INSERT と plans.status=succeeded への UPDATE を 1 トランザクションで実行
CREATE OR REPLACE FUNCTION finalize_plan(
  p_plan_id UUID,
  p_session_id UUID,
  p_items JSONB   -- plan_items の配列、JSON として受け取る
) RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
  -- 所有者再確認 + ロック取得済みかの再確認
  IF NOT EXISTS (
    SELECT 1 FROM plans
    WHERE id = p_plan_id AND session_id = p_session_id AND status = 'generating'
  ) THEN
    RAISE EXCEPTION 'plan not in generating state for owner';
  END IF;

  -- 既存の plan_items を削除（冪等性、リトライ時の重複防止）
  DELETE FROM plan_items WHERE plan_id = p_plan_id;

  -- 新規 plan_items を bulk INSERT
  INSERT INTO plan_items (id, plan_id, order_index, item_type, title, description,
                          start_time, end_time, place_id, place_name, lat, lng, address,
                          cost_jpy, cost_confidence, evidence, transit_to_next, notes)
  SELECT
    COALESCE((item->>'id')::UUID, gen_random_uuid()),
    p_plan_id,
    (item->>'order_index')::INTEGER,
    item->>'item_type',
    item->>'title',
    item->>'description',
    (item->>'start_time')::TIMESTAMPTZ,
    (item->>'end_time')::TIMESTAMPTZ,
    item->>'place_id',
    item->>'place_name',
    (item->>'lat')::DOUBLE PRECISION,
    (item->>'lng')::DOUBLE PRECISION,
    item->>'address',
    (item->>'cost_jpy')::INTEGER,
    item->>'cost_confidence',
    item->'evidence',
    item->'transit_to_next',
    item->>'notes'
  FROM jsonb_array_elements(p_items) AS item;

  -- status を succeeded に
  UPDATE plans SET status = 'succeeded', updated_at = NOW() WHERE id = p_plan_id;
END;
$$;
```

Python からは `supabase.rpc('finalize_plan', {'p_plan_id': ..., 'p_session_id': ..., 'p_items': items_json}).execute()` で呼ぶ。失敗時は例外として上がる。

失敗パス（LLM 4 回失敗 / storage 失敗）の status 遷移:

```sql
-- compare-and-set で 'generating' から 'failed' へ（競合耐性）
UPDATE plans SET status = 'failed', updated_at = NOW()
WHERE id = :plan_id AND status = 'generating';
```

### status 方針の一本化（v2、Codex Must-fix #2）

- lock 取得条件: `status IN ('draft', 'failed')` のみ（`generating` / `succeeded` は reject）
- `generating` への同時書き込みは 409 で拒否
- `succeeded` への再 generate は 409 で拒否（再生成は Phase 2 の `POST /api/plans/:id/regenerate` で別エンドポイント化）
- `failed` からの再生成は同一 plan_id で OK（plan_items を上書き）

### LLM 呼び出しの Structured Output（v2 で SDK API を厳格化、Codex Must-fix #3）

OpenAI SDK 1.58+ の `client.chat.completions.parse(response_format=<Pydantic Model>)`（GA 版、非 beta）を使う。v3 で `beta` 名前空間の記述を削除し、`client.chat.completions.parse` に統一（Codex v2 re-review 指摘、公式ドキュメント https://platform.openai.com/docs/guides/structured-outputs 準拠）。

利点:
- Pydantic model から自動で strict 対応 schema（全フィールド required + `additionalProperties: false`）を生成
- optional フィールドは `field: type | None` で表現 → `anyOf: [type, null]` + required に入れる（strict OK）
- parse 済み Pydantic インスタンスを直接受け取れる（JSON 手動 parse 不要）
- `refusal` フィールドが返ってきた場合の分岐を明示:

```python
completion = client.chat.completions.parse(
    model=model,
    messages=[...],
    response_format=LlmGeneratedPlan,
    timeout=PER_CALL_TIMEOUT_SEC,
)
choice = completion.choices[0]
if choice.message.refusal:
    # モデルが安全性理由で拒否した場合
    raise LlmRefusalError(choice.message.refusal)
parsed: LlmGeneratedPlan = choice.message.parsed
```

### Pydantic schema の strict 適合性担保

`LlmPlanItem` / `LlmGeneratedPlan` は全フィールド required + `model_config = ConfigDict(extra="forbid")` で `additionalProperties: false` を保証する。

optional な値（`description`, `place_id`, `cost_jpy`, `transit_ref`）は `Field(default=None)` ではなく `Field(...)` で明示 required にし、型に `| None` を付けることで null を許す（schema 上は `anyOf: [type, null]` + required）。Phase 1 内だと常にフル埋めが期待される。

### プロンプトとそのバージョニング

- `apps/api/src/llm/prompts/v1.0.0/` に system / user の 2 テキストファイル
  - `system.md` — evidence-pack.md の System Prompt 節を実ファイル化
  - `user_template.md` — evidence-pack.md の User Prompt Template 節を実ファイル化（`{evidence_pack_places_json}` 等の placeholder 付き）
- `PROMPT_VERSION` 環境変数（デフォルト `v1.0.0`）で切替。未設定時は `v1.0.0`
- プロンプトを pure text に出しておくと Codex / 人間のレビューが楽（Python リテラルに埋め込むと diff が荒れる）

### 出力 JSON Schema

evidence-pack.md の Schema をそのまま実装。ただし Pydantic で二重定義する:
- `LlmPlanItem`（_StrictBase）: LLM から受ける生の per-item
- `LlmGeneratedPlan`（_StrictBase）: `items: list[LlmPlanItem]`

OpenAI の `response_format` には Pydantic から `.model_json_schema()` で抽出した schema を渡す。これで LLM 出力 → Pydantic validate が自動になり、schema 違反は OpenAI 側で先に弾かれる。

### ハルシネーション検出 / Validator（v2 強化、Codex Must-fix #1）

`apps/api/src/llm/validator.py` の `validate_llm_output(plan: LlmGeneratedPlan, pack: EvidencePack) -> list[ValidationIssue]`:

| # | 検証項目 | エラー種別 | 補足 |
|---|---|---|---|
| 1 | schema 準拠 | — | Pydantic validate（SDK parse）が先行で担保、validator 到達時は成立前提 |
| 2 | item_type ごとの必須フィールド | MissingRequiredField | activity/meal/lodging → place_id 必須。transit → transit_ref 必須、place_id は null OK |
| 3 | place_id 実在 | UnknownPlaceId | item.place_id が pack.places の place_id セットに含まれる |
| 4 | 時刻順序 | InvalidTimeRange | start_time < end_time |
| 5 | 営業時間内 | OutsideOpeningHours | v2 で正規化済み `OpeningHoursSlot` を使い、start_time の曜日 + hour/min がスロット内にあるか厳密判定。opening_hours 空 / 24h 営業は block しない |
| 6 | transit edge 存在 | UnknownTransitEdge | item_type=transit の場合、transit_ref.from_place_id / to_place_id / mode に一致する edge が pack.transit_matrix に存在 |
| 7 | **transit departure_time 整合（v2 追加）** | TransitDepartureMismatch | transit_ref.departure_time が該当 edge.candidate_departures に含まれる |
| 8 | **transit duration 整合（v2 追加）** | TransitDurationMismatch | end_time - start_time が edge.duration_min に対し許容 ±5 分 |
| 9 | **transit fare 整合（v2 追加）** | TransitFareMismatch | item.cost_jpy == edge.fare_jpy（edge.fare_jpy が null なら item.cost_confidence == "unknown" 必須） |
| 10 | 予算超過 | BudgetExceeded | category 別合計が budget_constraints.breakdown_jpy を超えない。誤差許容 5% |
| 11 | 時系列重複 / 逆転 | OverlappingItems | order_index 昇順で並べたとき、item[i].end_time <= item[i+1].start_time |
| 12 | temporal 範囲 | OutOfTemporalRange | 全 items が temporal_constraints.start_datetime と end_datetime の範囲内 |
| 13 | **start_time の timezone 必須（v2 追加）** | MissingTimezone | ISO 8601 で offset が付いていること（JST +09:00 を要求）、`datetime.fromisoformat` で tzinfo is None なら reject |

返り値: `list[ValidationIssue]`（空なら成功、非空ならエラー集約）。retry プロンプトに issue を注入して LLM に自己訂正させる。

### opening_hours の事前正規化（v2 で追加、Codex Should-fix #6）

evidence-pack.md 正典（`"09:00-18:00"` のようなフォーマット）と現行 pack.py の Google weekdayDescriptions 生文字列保持の乖離を解消する。**Branch 0 で実装**:

```python
# apps/api/src/evidence/pack.py
class OpeningHoursSlot(_PackBase):
    day_of_week: Literal[0, 1, 2, 3, 4, 5, 6]  # 月=0 〜 日=6（Python datetime 互換）
    open_hhmm: str   # "09:00"
    close_hhmm: str  # "18:00"

class PlacePoint(_PackBase):
    ...
    opening_hours: list[OpeningHoursSlot]  # list[str] から変更
    opening_hours_raw: list[str] | None = None  # デバッグ用（weekdayDescriptions 原文、LLM には渡さない）
```

parser: `apps/api/src/evidence/opening_hours.py` を新規作成し、以下の形式をサポート:
- `"月曜日: 9時00分～17時00分"`（通常営業）
- `"月曜日: 24 時間営業"`（24h）→ `00:00-23:59` の slot 1 件
- `"月曜日: 定休日"`（closed）→ slot を生成しない
- `"月曜日: 11時00分～14時30分、17時00分～22時00分"`（ランチ/ディナー分割）→ slot 2 件
- parse 失敗時は警告ログ + その曜日を **"情報なし" フラグ付きの slot empty** として保持（`OpeningHoursSlot` ではなく `opening_hours_unknown_days: set[int]` に日 index を記録）→ validator はその曜日について **検証スキップ**（block しない、LLM の判断に任せる）

既存の `test_evidence_pack_models.py` / `test_evidence_places.py` を拡張して正規化テスト追加。

### リトライ + フォールバックポリシー（v2 でタイムアウト短縮、Codex Should-fix #3-13）

```
deadline: 全体 150 秒以内で完結（Render HTTP timeout 180 秒に設定）
per_call_timeout: 35 秒
max_retries_primary: 2（3 attempts 合計）
fallback_model: gpt-4o-mini（1 attempt のみ、残り deadline を超えないよう early abort）

attempt 1: gpt-4o (timeout 35s)
  ↓ ValidationIssue / OpenAI error
attempt 2: gpt-4o + previous_issues (timeout 35s)
  ↓ fail
attempt 3: gpt-4o + previous_issues (timeout 35s)
  ↓ fail
attempt 4: gpt-4o-mini + previous_issues (timeout 35s、残 deadline < 35s なら skip)
  ↓ fail
→ LlmGenerationError → 422
```

タイムアウト合計: 35×4 = 140 秒 + overhead 10 秒 = 150 秒以内。Render HTTP timeout は余裕を見て 180 秒に設定。

### plan_items 保存 + status 遷移（v2 で RPC 原子化）

上の「競合安全性」節の `finalize_plan(p_plan_id, p_session_id, p_items)` RPC を呼ぶだけ。`DELETE + INSERT + UPDATE` を 1 トランザクションで保証（Postgres の plpgsql は既定でトランザクション内実行）。

Python 実装:

```python
items_json = [serialize_item(item, plan_id) for item in generated.items]
try:
    get_supabase_client().rpc(
        "finalize_plan",
        {"p_plan_id": plan_id, "p_session_id": owner_session_id, "p_items": items_json},
    ).execute()
except Exception as e:
    # RPC 失敗 → status を 'failed' に（compare-and-set で競合耐性）
    _mark_failed(plan_id)
    raise
```

`_mark_failed` は `UPDATE plans SET status='failed' WHERE id=:id AND status='generating'` で、別プロセスが既に succeeded/failed に遷移させている場合は 0 行で no-op。

### plan_id owner 検証 + ロック取得（v3、RPC ベース）

route ハンドラ冒頭で上の `acquire_plan_generation_lock` RPC を呼ぶ。race は RPC 内で完結するので Flask 側はただ結果を分岐するだけ:

```python
result = get_supabase_client().rpc(
    "acquire_plan_generation_lock",
    {"p_plan_id": str(payload.plan_id), "p_session_id": g.owner_session_id},
).execute()
lock_result = result.data  # 'acquired' | 'not_found' | 'already_generating' | 'already_succeeded'

match lock_result:
    case "acquired":
        pass  # 続行
    case "not_found":
        return jsonify({"error": "plan not found"}), 404
    case "already_generating":
        return jsonify({"error": "plan is already being generated"}), 409
    case "already_succeeded":
        return jsonify({"error": "plan already succeeded, regenerate via Phase 2 endpoint"}), 409
    case _:
        current_app.logger.error(f"unexpected lock_result: {lock_result!r}")
        return jsonify({"error": "unexpected plan lock state"}), 500
```

### RPC 通信失敗時の曖昧ケース仕様化（v3、Codex v2 re-review 指摘）

Python から `rpc("finalize_plan", ...).execute()` を呼んだ後、**ネットワーク層で失敗**した場合（タイムアウト、HTTP 5xx、接続断）を考える。この時点でサーバー DB では:
- Case A: RPC が実行されず、plans.status は `generating` のまま
- Case B: RPC が commit 済みだが、レスポンスがクライアントに届かなかった（実際には成功）

Flask 側からは Case A と B を区別できない。そこで:

**方針**: **通信失敗時は `mark_plan_failed` を呼ばず、`status='generating'` のまま残す**。200 ではなく 504 (Gateway Timeout) を返す。フロントには「生成中、しばらく待ってから /plan/[id] を確認してください」と案内。

- Case A（未実行）: DB-3 の stuck cleanup（1 時間）で status='generating' の plan が削除される
- Case B（commit 済み）: フロントが後で /plan/[id] を開けば plan_items が読める → 成功扱いで UX は救済される

この方針だと、一時的な 504 で plan_items は後から取得可能 → 理想的な at-least-once セマンティクス。明示的に `mark_plan_failed` を呼ばないことで「成功したけど failed と誤認」を避ける。

### SDK バージョン固定（v3、Codex v2 re-review 指摘）

`apps/api/requirements.txt` で openai の下限バージョンを固定:

```
openai>=1.58,<2.0   # client.chat.completions.parse GA + response_format=Pydantic 対応
tiktoken>=0.7
```

openai 1.58 以降で `client.chat.completions.parse()` は beta ではなく GA、Pydantic 直渡しが安定。

### Flask app への blueprint 登録

既に `plan_routes` bp は登録済み。1.3d は同 bp の `POST /generate` を拡張するだけなので、追加の blueprint 登録は不要。

### コスト管理 / トークン制限

- `evidence_pack.places` は `name / category / lat / lng / opening_hours / price_level / rating / relevance_tags` だけ抽出してプロンプトへ（`address` / `user_ratings_total` は省略）
- `tiktoken` で user prompt のトークン数を計算、**12,000 トークン超なら警告ログ**（生成は続行）
- 1 生成あたりの想定コスト: gpt-4o で $0.10-0.30（llm-rules.md 準拠）

### `/api/plans/generate` のレスポンス形状変更

v1.3c: `{ "plan_id": null }` （debug mode で `evidence_pack` も）  
v1.3d: `{ "plan_id": <UUID> }` （debug mode は廃止 → shared-types 汚染しないため）

破壊的変更だがフロントは `{ "plan_id": null }` ではなく `plan_id` だけを見る設計になっている（`generating/page.tsx` L101〜）。mock mode との両立は維持される。

### Error code 対応表

| 事象 | ステータス |
|---|---|
| JWT 欠落 / 無効 | 401 |
| 413 body too large / Pydantic 違反 | 400 |
| evidence_pack_id が期限切れ / 未知 / owner 不一致 | 404 |
| Transit Validator 違反 | 400 |
| plan_id 未知 / plan owner 不一致 | 404 |
| plan.status が `generating` で二重 generate 試行 | 409 |
| plan.status が `succeeded` で再書き込み不可 | 409 |
| LLM 失敗 4 回（ハルシネーション含む） | 422 |
| OpenAI API 通信失敗（タイムアウト/5xx）× 4 | 502 |
| finalize_plan RPC 通信失敗（commit 済か不明） | 504（status は generating のまま、DB-3 stuck cleanup が救済） |
| Supabase 通信失敗（lock 取得 / mark_failed など） | 500 |

---

## Task 0: opening_hours 正規化（Branch 0: `feat/opening-hours-normalization`）

**Why**: evidence-pack.md 正典と pack.py 実装のズレ（weekdayDescriptions 生文字列 vs `"09:00-18:00"` 形式）を解消。validator が厳密な営業時間判定を書けるようになる。

### ファイル構造

**新規:**
- `apps/api/src/evidence/opening_hours.py` — `parse_weekday_descriptions(descriptions: list[str]) -> list[OpeningHoursSlot]`
- `apps/api/tests/test_opening_hours_parser.py`

**変更:**
- `apps/api/src/evidence/pack.py` — `PlacePoint.opening_hours: list[OpeningHoursSlot]` + `OpeningHoursSlot` class
- `apps/api/src/evidence/places.py` — Places API レスポンスを正規化して `PlacePoint` に渡す
- `apps/api/tests/test_evidence_places.py` / `test_evidence_pack_models.py` — 正規化後構造での testdata 更新

### Step-by-step

- [ ] **Step 1: `OpeningHoursSlot` Pydantic モデル + parser の TDD**

- [ ] **Step 2: places.py を parser 経由に切替、既存テスト通過確認**

- [ ] **Step 3: コミット提案（Branch 0）**

メッセージ案: `refactor(phase-1.3d): PlacePoint.opening_hours を構造化（OpeningHoursSlot）+ 日本語 weekdayDescriptions パーサ`

---

## Task 1: LLM prompt builder + 出力 validator（Branch A: `feat/llm-prompt-and-validator`）

### ファイル構造

**新規:**
- `apps/api/src/llm/__init__.py`
- `apps/api/src/llm/prompts/v1.0.0/system.md`
- `apps/api/src/llm/prompts/v1.0.0/user_template.md`
- `apps/api/src/llm/prompt.py` — `build_system_prompt(version)`, `build_user_prompt(merged_pack, previous_issues=[], version)`, `load_prompt_version()`
- `apps/api/src/llm/schema.py` — `LlmPlanItem`, `LlmGeneratedPlan`（Pydantic）+ `llm_output_json_schema()` ヘルパ
- `apps/api/src/llm/validator.py` — `ValidationIssue`, `validate_llm_output(plan, pack) -> list[ValidationIssue]`
- `apps/api/tests/test_llm_prompt.py`
- `apps/api/tests/test_llm_schema.py`
- `apps/api/tests/test_llm_validator.py`

**変更:** なし（OpenAI 接続は Task 2）

### Step-by-step

- [ ] **Step 1: プロンプトファイル作成**

`system.md` は evidence-pack.md の System Prompt 節をそのまま転記。`user_template.md` は placeholder 付き:

```
# 旅行の基本情報
{query_context_json}

# 利用可能なスポット (Evidence Pack)
{evidence_pack_places_json}

# 経路情報（スポット間の移動）
{transit_matrix_json}

# 予算制約
{budget_constraints_json}

# 時間制約
{temporal_constraints_json}

# 前回の生成で失敗した検証項目（あれば修正せよ）
{previous_issues_json}

上記情報のみを使ってプランを JSON で生成せよ。
```

- [ ] **Step 2: `LlmPlanItem` / `LlmGeneratedPlan` Pydantic 定義**

`schema.py` に `_StrictBase` 継承で定義。`transit_ref` は optional の nested model。evidence-pack.md の JSON Schema に 1:1 対応。`model_json_schema()` で strict=True の schema を取得可能にする。

- [ ] **Step 3: `ValidationIssue` と `validate_llm_output` の TDD**

`test_llm_validator.py` を先に書く:
- happy path（全検証通過）
- unknown place_id
- invalid time range
- opening hours 違反（best-effort 判定）
- unknown transit edge
- budget exceeded
- overlapping items
- out of temporal range
- validator output が `list[ValidationIssue]` で pretty printable

Red 確認 → 実装 → Green。

- [ ] **Step 4: `build_user_prompt` のテスト**

- モックの merged_pack / previous_issues を渡して文字列が整形されることを確認
- previous_issues=[] の場合は「前回の検証項目: なし」等に展開
- token count（tiktoken）が計算されログに記録されること

- [ ] **Step 5: コミット提案（Branch A）**

対象:
```
apps/api/src/llm/__init__.py
apps/api/src/llm/prompts/v1.0.0/system.md
apps/api/src/llm/prompts/v1.0.0/user_template.md
apps/api/src/llm/prompt.py
apps/api/src/llm/schema.py
apps/api/src/llm/validator.py
apps/api/tests/test_llm_prompt.py
apps/api/tests/test_llm_schema.py
apps/api/tests/test_llm_validator.py
```

メッセージ案: `feat(phase-1.3d): LLM プロンプトビルダー + 出力検証モジュール（プロンプト v1.0.0、ハルシネーション 7 項目）`

---

## Task 2: OpenAI generator + retry/fallback + atomic finalize RPC（Branch B: `feat/llm-generator-atomic`）

**Branch B 分割の理由（Codex Should-fix #10）**: v1 では generator + route + storage を 1 ブランチにまとめて肥大化していた。v2 では **generator（LLM 呼び出し層）と RPC（DB 保存層）だけ** を Branch B に閉じ、route 配線は Branch C に分離する。

### ファイル構造

**新規:**
- `apps/api/src/llm/generator.py` — `generate_plan(pack, *, client, ...) -> LlmGeneratedPlan`（retry + fallback + deadline）
- `supabase/migrations/20260424_04_plan_generation_rpcs.sql` — `acquire_plan_generation_lock` + `mark_plan_failed` + `finalize_plan` の 3 つの Postgres 関数 + `plan_lock_result` enum
- `apps/api/src/plans/__init__.py`
- `apps/api/src/plans/storage.py` — `try_lock_plan_for_generation(plan_id, owner_session_id)`, `call_finalize_plan(plan_id, owner_session_id, items)`, `mark_plan_failed(plan_id, owner_session_id)`（いずれも薄い RPC ラッパ）
- `apps/api/tests/test_llm_generator.py` — mocked OpenAI
- `apps/api/tests/test_plans_storage.py` — mocked Supabase

**変更:**
- `apps/api/requirements.txt` — `openai>=1.58,<2.0` に下限上げ + `tiktoken>=0.7` 追加

### Step-by-step

- [ ] **Step 1: `supabase/migrations/20260424_04_plan_generation_rpcs.sql` 作成**

以下 3 つの関数 + enum を含む:
- `CREATE TYPE plan_lock_result AS ENUM (...)` — DO ブロックで `pg_type` 存在確認して冪等化（上の「lock 取得 RPC」節の通り）
- `acquire_plan_generation_lock(p_plan_id, p_session_id)` — v3 競合安全性節の定義
- `mark_plan_failed(p_plan_id, p_session_id)` — v3 競合安全性節の定義（2 引数、owner_session_id を WHERE 句で照合）
- `finalize_plan(p_plan_id, p_session_id, p_items)` — v2 plan_items 原子保存節の定義

ユーザが Supabase SQL Editor で手動適用 → `docs/data-model.md` に追記。冪等化:
- 関数は `CREATE OR REPLACE FUNCTION` で上書き可能
- enum は DO ブロックで存在チェックして作成
- migration を 2 回実行しても同じ結果

- [ ] **Step 2: `plans/storage.py` の TDD（v3 では全て RPC 薄ラッパ）**

3 関数はいずれも Supabase `rpc(...)` を呼ぶだけの薄い関数（Python 側に race は発生しない）:

- `try_lock_plan_for_generation(plan_id, owner_session_id) -> LockResult`  
  - `LockResult = Literal["acquired", "not_found", "already_generating", "already_succeeded"]`
  - `rpc("acquire_plan_generation_lock", {"p_plan_id": ..., "p_session_id": ...})` を呼び data を返す
- `call_finalize_plan(plan_id, owner_session_id, items: list[dict])`
  - `rpc("finalize_plan", {"p_plan_id": ..., "p_session_id": ..., "p_items": items})` を呼び例外を伝播
  - **通信失敗（タイムアウト / ConnectionError）は `RpcTransportError` にラップして呼び出し側で 504 を返せるように** する（v3 RPC 通信失敗仕様化）
- `mark_plan_failed(plan_id, owner_session_id)`
  - `rpc("mark_plan_failed", {"p_plan_id": ..., "p_session_id": ...})` を呼ぶ。失敗してもログのみ（fire-and-forget 的、呼び出し元は既にエラー応答を返す段階）

mocked Supabase client で各パス検証。LockResult 4 種、call_finalize_plan 成功 / RpcTransportError 両方、mark_plan_failed の例外時無例外伝播を unit で担保。

- [ ] **Step 3: `generator.py` の TDD**

- happy path: 1 回目成功
- retry: 1 回目 ValidationIssue → 2 回目成功、issues が prompt に含まれる
- fallback: primary 3 回失敗 → gpt-4o-mini 1 回成功
- 完全失敗: 4 回失敗 → LlmGenerationError
- deadline 超過: 残 deadline < per_call_timeout なら早期 abort → `DeadlineExceededError`
- OpenAI タイムアウト / 429 / 5xx は retry カウントに含める
- `response_format=LlmGeneratedPlan` を Pydantic 直渡しで呼ぶ、`refusal` 分岐ハンドル
- tiktoken トークン数が 12,000 超えたら warning ログ

- [ ] **Step 4: コミット提案（Branch B）**

対象:
```
apps/api/requirements.txt
apps/api/src/llm/generator.py
apps/api/src/plans/__init__.py
apps/api/src/plans/storage.py
apps/api/tests/test_llm_generator.py
apps/api/tests/test_plans_storage.py
supabase/migrations/20260424_04_plan_generation_rpcs.sql
```

メッセージ案: `feat(phase-1.3d): OpenAI Structured Output generator（retry×3 + gpt-4o-mini fallback、deadline 150s）+ finalize_plan RPC（compare-and-set lock）`

---

## Task 3: `/api/plans/generate` 最終配線 + debug mode 廃止（Branch C: `feat/plans-generate-route`）

### ファイル構造

### ファイル構造

**変更:**
- `apps/api/src/routes/plan_routes.py` — lock 取得 + LLM 生成 + RPC 保存 + `{ plan_id }` レスポンス、debug mode 削除
- `apps/api/tests/test_routes_plans.py` — LLM + 保存周り追加

### Step-by-step

- [ ] **Step 1: plan_routes.py の最終化**

```python
# 1. JWT / Pydantic validate / load_pack / transit validate まで既存通り
# 2. Lock 取得（compare-and-set）
lock = try_lock_plan_for_generation(str(payload.plan_id), g.owner_session_id)
if lock != "acquired":
    return _lock_failure_response(lock)  # 404 or 409

# 3. LLM 生成
try:
    generated = generate_plan(merged)
except LlmGenerationError as e:
    mark_plan_failed(str(payload.plan_id), g.owner_session_id)
    current_app.logger.info(f"LLM failed: {len(e.issues)} issues after {e.attempts} attempts")
    return jsonify({"error": "plan generation failed after retries"}), 422
except LlmTransportError as e:
    mark_plan_failed(str(payload.plan_id), g.owner_session_id)
    current_app.logger.warning(f"OpenAI transport error: {e}")
    return jsonify({"error": "plan generation service unavailable"}), 502

# 4. 原子保存 RPC
items = [_serialize_plan_item(item, payload.plan_id) for item in generated.items]
try:
    call_finalize_plan(str(payload.plan_id), g.owner_session_id, items)
except RpcTransportError as e:
    # 通信失敗: commit 済か未実行か不明。mark_plan_failed は呼ばず、status=generating のまま残して
    # DB-3 の stuck cleanup（1 時間）に救済を委ねる。Case B（実際は成功）ならフロント再訪で plan_items が読める
    current_app.logger.warning(f"finalize_plan transport error (status left as generating): {e}")
    return jsonify({"error": "plan save unclear, please retry after checking /plan/<id>"}), 504
except Exception as e:
    # 明示的失敗（RPC 内で例外）: status を failed に
    mark_plan_failed(str(payload.plan_id), g.owner_session_id)
    current_app.logger.exception(f"finalize_plan failed: {e}")
    return jsonify({"error": "failed to save generated plan"}), 500

return jsonify({"plan_id": str(payload.plan_id)}), 200
```

- [ ] **Step 2: debug mode 廃止 + 既存テスト書き換え**

- `?debug=1` 分岐削除
- `test_happy_path_debug_mode_returns_merged_pack` を削除
- `test_happy_path_default_returns_only_plan_id_null` を「LLM 成功時 { plan_id: UUID }」に書き換え

- [ ] **Step 3: 追加テストケース**

mocked `try_lock_plan_for_generation` / `generate_plan` / `call_finalize_plan`:
- ロック取得失敗: `not_found` → 404, `already_generating` → 409, `already_succeeded` → 409
- LLM 422 → status=failed, エラーレスポンス
- LLM transport 502 → status=failed, 502
- 成功 → `{plan_id: UUID}` + finalize_plan 呼ばれる
- 保存失敗（明示例外） → status=failed, 500
- 保存失敗（RpcTransportError） → status は generating のまま (mark_plan_failed 呼ばれない), 504

- [ ] **Step 4: integration テスト 3 件化（Codex Should-fix #12）**

既存の `test_integration_evidence_to_generate_round_trip` を **plan_id 付与** + **LLM 実呼び出し** + 以下 3 件にばらす:

1. **成功パス**: 実 OpenAI 呼び出し → plan_items 保存確認 → 後処理で plans/plan_items 削除
2. **ロック競合（409）**: 既に generating な plan に対して generate を試行 → 409
3. **不正入力（validator 失敗で 400）**: transit_matrix に Evidence Pack 外の place_id を混ぜて送る → 400

（fallback 経路の integration は時間とコストかかるので unit で十分、integration では省略）

- [ ] **Step 5: コミット提案（Branch C）**

対象:
```
apps/api/src/routes/plan_routes.py
apps/api/tests/test_routes_plans.py
```

メッセージ案: `feat(phase-1.3d): /api/plans/generate 最終配線（compare-and-set lock + LLM 生成 + finalize_plan RPC + debug mode 廃止）`

---

## Task 4: DB-2 RLS E2E テスト + DB-3 pg_cron クリーンアップ（Branch D: `feat/db-integrity-sweep`）

### ファイル構造

**新規:**
- `apps/api/tests/test_rls.py` — integration marker
- `supabase/migrations/20260424_03_cleanup_cron.sql` — pg_cron 設定（冪等）

**変更:** なし

### Step-by-step

- [ ] **Step 1: `test_rls.py` 実装（Codex Should-fix #8）**

PostgREST のエラーコードで厳密に検証し、service_role 経路との違いも明示:

```python
@pytest.mark.integration
@pytest.mark.skipif(not _has_full_stack(), reason="full stack env required")
def test_anon_client_blocks_cross_session_select(...):
    """user_a が INSERT した plan を user_b の anon client で SELECT → 0 行。

    PostgREST は RLS の SELECT 拒否を「エラー」ではなく「0 行返却」で表現する。
    テストは data リストの長さ + maybe_single() の data is None で厳密に検証する。
    """
    # 1. anon_a / anon_b の 2 匿名ユーザを作成（両方 anon key で別クライアント）
    # 2. anon_a が plans を INSERT（成功、INSERT レスポンスに data[0] 含まれる）
    # 3. anon_b が同 plan_id を SELECT → result.data == [] を厳密アサート
    # 4. anon_b が .single() で取ると PostgrestAPIError が raise される（code='PGRST116' not found）
    # 5. cleanup: service_role で両ユーザ削除

@pytest.mark.integration
def test_anon_client_cannot_update_or_delete_others_row(...):
    """UPDATE / DELETE はエラーにはならないが 0 行影響になる（PostgREST の RLS 挙動）。
    data 配列長で厳密に 0 行を確認する。"""
    # anon_a が INSERT、anon_b が UPDATE を試行:
    #   resp = anon_b.from_("plans").update({"title": "hacked"}).eq("id", plan_id).execute()
    #   assert resp.data == []
    # 同様に DELETE も resp.data == []
    # 最後に anon_a で SELECT して title が変わっていないことを確認（実際に write されていない）

@pytest.mark.integration
def test_service_role_bypasses_rls_for_shared_access(...):
    """service_role クライアントは RLS をバイパス。DB-5 の共有 API 実装で使う前提。"""
    # 1. anon_a が plan を作り、service_role で share_token を付与（UPDATE）
    # 2. anon_b の anon client で SELECT ... WHERE share_token = X → data=[]（RLS で遮断）
    # 3. service_role クライアントで SELECT ... WHERE share_token = X → 1 行（RLS バイパス）

@pytest.mark.integration
def test_evidence_pack_sessions_anon_blocked(...):
    """evidence_pack_sessions は RLS ON + ポリシー無しで anon から完全遮断。

    anon は INSERT / SELECT 全て 0 行 or エラー。テストは data=[] + 42501 エラーコード
    （「permission denied for table」）のどちらかを expect する。
    """
    # anon client で SELECT → data == []（RLS 無ポリシーなので 0 行、エラーは起きない）
    # anon client で INSERT → PostgrestAPIError code='42501' を expect
    # service_role client で SELECT / INSERT → 両方成功
```

- [ ] **Step 2: `supabase/migrations/20260424_03_cleanup_cron.sql`（冪等化、Codex Should-fix #9）**

```sql
-- pg_cron を有効化（Supabase では事前に Extensions タブで pg_cron を ON にする必要あり）
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- 既存ジョブがあれば unschedule（再実行時の重複 schedule を防ぐ）
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-evidence-pack-sessions') THEN
    PERFORM cron.unschedule('cleanup-evidence-pack-sessions');
  END IF;
  IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-stuck-plans') THEN
    PERFORM cron.unschedule('cleanup-stuck-plans');
  END IF;
  IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-abandoned-plans') THEN
    PERFORM cron.unschedule('cleanup-abandoned-plans');
  END IF;
END $$;

-- evidence_pack_sessions: 期限切れを 1 時間毎に削除
SELECT cron.schedule(
  'cleanup-evidence-pack-sessions',
  '0 * * * *',
  $$DELETE FROM evidence_pack_sessions WHERE expires_at < now()$$
);

-- plans stuck generating: 1 時間毎、updated_at から 1 時間超過を削除
SELECT cron.schedule(
  'cleanup-stuck-plans',
  '5 * * * *',
  $$DELETE FROM plans WHERE status = 'generating' AND updated_at < now() - INTERVAL '1 hour'$$
);

-- plans 失敗 / draft: 1 日毎、24 時間超過を削除
SELECT cron.schedule(
  'cleanup-abandoned-plans',
  '0 3 * * *',
  $$DELETE FROM plans WHERE status IN ('draft', 'failed') AND created_at < now() - INTERVAL '24 hours'$$
);
```

`docs/data-model.md` に「cron ジョブは DB-1 の migrations 運用開始後に正典化」と注記。
Manato が Supabase SQL Editor で手動適用（Extensions タブで pg_cron を有効化することが前提）。

- [ ] **Step 3: コミット提案（Branch D）**

対象:
```
apps/api/tests/test_rls.py
supabase/migrations/20260424_03_cleanup_cron.sql
```

メッセージ案: `feat(db-2,db-3): RLS 他セッション遮断の integration テスト + pg_cron クリーンアップ（冪等化、evidence_pack_sessions / stuck plans / abandoned plans）`

---

## 実装フロー（v2、5 ブランチ）

### 順序
1. **Branch 0**（opening-hours-normalization）→ develop マージ
2. **Branch A**（llm-prompt-and-validator）→ develop マージ（Branch 0 依存）
3. **Branch B**（llm-generator-atomic）→ develop マージ（Branch A 依存、finalize_plan RPC を Supabase SQL Editor に手動適用）
4. **Branch C**（plans-generate-route）→ develop マージ（Branch B 依存）
5. **Branch D**（db-integrity-sweep）→ develop マージ（他ブランチと独立、並列可）

### 各ブランチの検証
- `pnpm --filter api test`（unit）全 PASS
- Branch C のみ `pytest -m integration` で 3 件（success / lock conflict 409 / invalid input 400）PASS
- Branch D の integration テストは Supabase の anon/service_role 両方使うので環境変数必須
- tsc は変更なし（shared-types / schemas は Phase 1.3c+ で同期済み、本計画で追加なし）

### Codex レビュー
- 本計画の v1 → v2 レビュー（このタイミング）
- Branch B 実装完了後、`generator.py` + `storage.py` + `finalize_plan` SQL を中心に実装レビュー（最重要、競合安全性 + ハルシネーション対策）
- Branch C 実装完了後、`plan_routes.py` の最終化をレビュー

### デプロイ関連の追記（Codex Should-fix #14）
- `.env.example` に `PROMPT_VERSION=v1.0.0`（optional、デフォルト v1.0.0）を追記
- `docs/setup-guide.md` に「Render の HTTP timeout を 180 秒に引き上げる」手順を追記
- `docs/setup-guide.md` に「Supabase Extensions タブで pg_cron を有効化する」手順を追記
- `docs/setup-guide.md` に「`finalize_plan` RPC を Supabase SQL Editor で適用する」手順を追記

---

## 懸念 / 未決事項（v2）

- **OpenAI の `strict: true` は 2024-08 以降 GPT-4o-2024-08-06+ で対応**。2026-04 時点では確実に使えるはずだが、API 変更があれば実装時に調整（`client.chat.completions.parse` で Pydantic 直渡しが最新推奨パス、SDK 1.58+ GA）
- **Render HTTP timeout**: デフォルト 100 秒。最悪 4×35=140 秒 + overhead 10 秒 = **150 秒以内** なので、Render の HTTP timeout を **180 秒に設定**（バッファ込み）→ `docs/setup-guide.md` に追記
- **opening_hours parse 失敗時**: 該当曜日は `opening_hours_unknown_days` セットに登録し、validator は **その曜日の検証をスキップ**（block せず LLM の判断を通す）。safety と UX のトレードオフで後者を優先（parse ルールをケチると全部 reject されて UX が壊れるため）
- **LLM 出力の `start_time` タイムゾーン**: system prompt で「JST (+09:00) を明示した ISO 8601」を要求。validator で `tzinfo is not None` をチェック（チェック項目 #13）
- **transit item の cost_jpy**: LLM が `fare_jpy` を参照して埋める設計。transit edge の `fare_jpy` が null の場合、LLM に `cost_confidence = "unknown"` を要求（validator #9 で強制）
- **プロンプトトークン 12,000 超**: warning ログのみ（生成続行）。将来対策は Evidence Pack 側で places を上位スコアで絞る（Phase 2 で実装）
- **`PROMPT_VERSION` は切替のみ、A/B は将来拡張（Codex Should-fix #11）**: 同時割当 / 結果ログ比較は Phase 1.3e として別タスク化。Phase 1 は PROMPT_VERSION=v1.0.0 固定でよい

## Nice-to-have（余力があれば）

- プロンプトの A/B テスト環境（Phase 1.3e で正式化: 割当ロジック + llm_call_logs テーブル + cost/accuracy 比較ダッシュボード）
- LLM 入出力のサンプリング保存（Supabase の `llm_call_logs` テーブル、個人情報なし、後のプロンプト改善用）
- Embedding-based relevance_tags 付与（Phase 2 以降）

---

## 自己レビュー（Self-Review）

### スコープ coverage
- [x] `apps/api/src/llm/prompt.py`, `schema.py`, `validator.py`, `generator.py`（Task 1, 2）
- [x] `/api/plans/generate` の最終応答を `{ plan_id }` に戻す（Task 2 Step 3-4）
- [x] plan_items を Supabase に保存（Task 2 Step 1, 3）
- [x] リトライ最大 2 回 + fallback（Task 2 Step 2）
- [x] 10 回生成して架空スポット出力率 0% の検証 → integration テストで 3 回以上 happy path を通せば十分な代替。10 回は手動で確認（setup-guide に手順記載）
- [x] DB-2（Task 3 Step 1）
- [x] DB-3（Task 3 Step 2）

### 型一貫性チェック
- `LlmPlanItem`（新規、_StrictBase）→ `PlanItem`（schemas、Supabase テーブル行）への変換は `_serialize_plan_item`（plan_routes.py 内 private）
- `PlanStatus` は schemas に既存（1.3c+ で同期済み）、Task では import するだけ
- `OpeningHoursSlot` は Branch 0 で新規追加、shared-types には出さず（サーバー内部構造、LLM プロンプトにのみ渡す）

### 1.3d 後の 2.x への橋渡し
- プロンプトバージョニングを入れたので将来の A/B テスト拡張が可能
- `relevance_tags` は 1.3d で LLM が評価する場所を空けてあるので、Phase 2 で Embedding 付与に置き換え可能
- debug mode 廃止で shared-types 汚染なし、破壊的変更なし
- finalize_plan RPC は Phase 2.4（部分再生成）で「単一アイテムのみ UPDATE」する亜種を追加するだけで済む構造
