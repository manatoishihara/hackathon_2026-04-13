# Phase 1.3c 実装計画 — Transit Validator + `/api/plans/generate` 骨組み

> **For agentic workers:** 本計画はチェックボックス（`- [ ]`）で進捗管理する。Task 単位でコミット提案を出す（ユーザが手動でコミット）。
>
> **Revision history:**
> - 2026-04-21 v1: 初版
> - 2026-04-21 v2: Codex レビュー反映（DoS hard cap / required 型 / UUID / dedupe 矛盾検出 / 距離上限 / 3 点同期順序 / テスト穴）
> - 2026-04-21 v3: Codex re-review 反映（setdefault → 直接代入 / hard cap テスト偽陽性修正 / ログ PII 対策 / integration skip の穴塞ぎ / candidate_departures 順序差分の明文化）

**Goal:** フロント Maps JS SDK で組み立てた `transit_matrix` をサーバー側で厳密検証し、サーバー短期キャッシュから取り出した Evidence Pack に merge する骨組みを作る（LLM はまだ呼ばない、1.3d で接続）。

**Architecture:** 既存の `routes/evidence_routes.py` と同型の Flask blueprint パターン。Transit Validator は純関数として `evidence/validator.py` に配置し、ルート関数はそれを呼ぶだけの薄い wrapper に保つ。`PlanGenerationPayload` は docs/data-model.md の計画節から実型へ昇格し、3 点同期（docs / shared-types / Pydantic）を **docs 先行** で実施。1.3c のレスポンスは「debug 用」の opt-in (`?debug=1`) で `{ plan_id: null, evidence_pack: <merged pack dict> }` を返す（通常レスポンスは `{ plan_id: null }` のみで、1.3d で `{ plan_id }` に差し替え）。

**Tech Stack:** Flask Blueprint / Pydantic v2 / pytest（mock 認証 + mock cache の unit、live Supabase の integration）

---

## 前提 / 判断分岐の確定（Codex レビュー反映版）

### Validator の責務（Pydantic 層の外で担保する文脈依存検証）
- Pydantic 層（`ClientTransitEdge`）で値域・文字長・HH:mm はガード済み
- サーバー validator が担保するのは以下 5 点:
  1. `from_place_id` / `to_place_id` が `EvidencePack.places` の `place_id` セットに含まれる → ValidationError
  2. `from_place_id == to_place_id`（自己ループ）は ValidationError
  3. 件数上限: `min(HARD_CAP=200, N*(N-1))` を **正規化後件数** で判定。超過は ValidationError
  4. `(from_place_id, to_place_id, mode)` 3-tuple の重複:
     - **完全一致**（全フィールド値が同じ）→ silently drop（フロントのリトライ耐性のため）
     - **矛盾**（key 一致で他フィールド値が違う）→ ValidationError（隠蔽リスク）
  5. **距離上限**: `haversine_km(from, to) > 15.0` は ValidationError（フロントは 10km フィルタ、浮動小数点誤差 + 将来余裕で 15km）
- 返値: `list[TransitEdge]`（pack.py）。dedupe 済み、順序は入力順で安定化
- 例外クラス: `TransitMatrixValidationError(ValueError)`

### `PlanGenerationPayload` の型定義（Codex 修正後）
- `evidence_pack_id: UUID` — Pydantic の標準 `UUID` 型で正規表現不要 + JSON シリアライズは自動で string
- `transit_matrix: list[ClientTransitEdge] = Field(max_length=200)` — **required**（default を外す）+ **静的 hard cap 200** で先入れパース負荷を抑える
- TS 側は `string` / `ClientTransitEdge[]` のまま（TS に UUID 型がない、配列は required で表現）

### Flask `MAX_CONTENT_LENGTH`
- `create_app` で **直接代入** `app.config["MAX_CONTENT_LENGTH"] = 256 * 1024` (256KB)
  - Codex re-review High 指摘: `setdefault` は Flask 既定値 `None` を上書きしないため効かない。直接代入で確実にかける
- 200 edges × 各 ~1KB（route_summary 最大 120 chars + UUID 等）+ overhead = 余裕を見て 256KB（UTF-8 マルチバイト最悪ケースでも 200KB 以内に収まる想定）
- 413 Request Entity Too Large がフロントで出るため、既存 HTTPException ハンドラで JSON に変換される（`app.py` の `@app.errorhandler(HTTPException)` は維持）

### エラーコード表
| 事象 | ステータス |
|---|---|
| JWT 欠落 / 無効 | 401 |
| body サイズ超過 | 413（Flask 標準） |
| request body が JSON object でない | 400 |
| `PlanGenerationPayload` Pydantic 違反（値域 / 長さ / HH:mm / hard cap / UUID 形式） | 400 |
| `evidence_pack_id` が期限切れ / 未知 / owner 不一致 | 404（内部ログに reason code） |
| Transit Validator 違反（place_id 所属 / 自己ループ / 件数 / 距離 / 矛盾重複） | 400 |
| `load_pack` が raise（DB 障害） | 500（スタックトレースをログ） |

### 1.3c の応答形状
- デフォルト: `{ "plan_id": null }` だけを返す（透明な骨組み）
- `?debug=1` が付いた時のみ: `{ "plan_id": null, "evidence_pack": <merged pack dict> }` を返す（テストと開発確認用）
  - これにより 1.3d で `{ "plan_id": <UUID> }` に差し替える際にフロントのコードパスを壊さない
  - `debug` クエリパラメータは shared-types に含めず、バックエンド内部の切替のみ

### 3 点同期の順序（docs-model-sync 遵守）
1. **docs/data-model.md** を先に更新（計画節 → 実型セクションに昇格）
2. **packages/shared-types/src/index.ts** 同期
3. **apps/api/src/schemas/__init__.py** 同期
4. **apps/api/tests/test_schema_parity.py** 更新
5. `pnpm test` で全 PASS 確認

---

## ファイル構造

**新規作成:**
- `apps/api/src/evidence/validator.py`
- `apps/api/src/routes/plan_routes.py`
- `apps/api/tests/test_evidence_validator.py`
- `apps/api/tests/test_routes_plans.py`

**変更:**
- `apps/api/src/app.py` — `plan_routes` blueprint 登録 + `MAX_CONTENT_LENGTH` 設定
- `apps/api/src/schemas/__init__.py` — `PlanGenerationPayload` + `__all__` 更新
- `packages/shared-types/src/index.ts` — `PlanGenerationPayload` 実型追加、計画節コメント整理
- `apps/api/tests/test_schema_parity.py` — `EXPECTED_FIELDS` + `_MODELS` 追加
- `docs/data-model.md` — 計画節 → 実型移動
- `tasks/todo.md` — 1.3c チェックボックス更新（最後）

---

## Task 1: `PlanGenerationPayload` の 3 点同期（docs 先行）

**Files:**
- Modify: `docs/data-model.md`
- Modify: `packages/shared-types/src/index.ts`
- Modify: `apps/api/src/schemas/__init__.py`
- Modify: `apps/api/tests/test_schema_parity.py`

### Step 1 — docs/data-model.md を先に更新 **（docs 先行）**

- [ ] **Step 1.1: 計画節「Phase 1.3 で追加予定の型（API 分割に伴う）」から `PlanGenerationPayload` 定義を削除**
- [ ] **Step 1.2: 「TypeScript 型定義」セクションの「API リクエスト/レスポンス」に実型として追加:**

```typescript
// POST /api/plans/generate リクエスト（Phase 1.3c で実型化）。
// evidence_pack_id はサーバー短期キャッシュ (evidence_pack_sessions.id) の UUID。
// transit_matrix はフロントが Maps JS SDK DirectionsService で組み立てた有向エッジ配列。
// サーバー側は place_id 所属 / 自己ループ / 件数上限 / 距離上限 / 矛盾重複 を検証する。
// 件数は最大 200（サーバー hard cap、フロント実装は 40 前後）。
export type PlanGenerationPayload = {
  evidence_pack_id: string; // UUID 文字列
  transit_matrix: ClientTransitEdge[];
};
```

- [ ] **Step 1.3: 「API リクエスト/レスポンス」直上の `ClientTransitEdge` の節からも "Phase 1.3b で昇格" の注記を最新化（不要）**

計画節は `ClientTransitEdge` も `PlanGenerationPayload` もどちらも実コード化済みの注記に差し替える。

### Step 2 — shared-types 同期

- [ ] **Step 2.1: `packages/shared-types/src/index.ts` の「API リクエスト/レスポンス」末尾に追加**

```typescript
// POST /api/plans/generate リクエスト（Phase 1.3c で実型化）。
// evidence_pack_id はサーバー短期キャッシュ (evidence_pack_sessions.id) の UUID。
// transit_matrix の要素制約は ClientTransitEdge（Phase 1.3b）。サーバー側は
// 件数最大 200、距離 15km 以内、place_id 所属、矛盾重複禁止で検証する。
export type PlanGenerationPayload = {
  evidence_pack_id: string;
  transit_matrix: ClientTransitEdge[];
};
```

- [ ] **Step 2.2: ビルド確認**

```bash
pnpm --filter shared-types build
```

### Step 3 — Pydantic 同期

- [ ] **Step 3.1: `apps/api/src/schemas/__init__.py` に追加**

```python
from uuid import UUID

class PlanGenerationPayload(_StrictBase):
    """POST /api/plans/generate リクエスト（Phase 1.3c で実型化）。

    - evidence_pack_id: evidence_pack_sessions.id の UUID。str ではなく UUID 型で
      先パース段階で形式違反を弾く（DoS + 改ざん対策）。`model_dump(mode="json")` で
      文字列にシリアライズされるので TS 側の `string` 契約と整合する。
    - transit_matrix: required（default なし）。max_length=200 の静的 hard cap で
      巨大ペイロードを先パース段階で 413 相当に弾く。文脈依存の検証（place_id 所属 /
      自己ループ / 距離 / 矛盾重複）は evidence.validator.validate_client_transit_matrix で。
    """

    evidence_pack_id: UUID
    transit_matrix: list[ClientTransitEdge] = Field(max_length=200)
```

- [ ] **Step 3.2: `__all__` に `"PlanGenerationPayload"` を追加**

### Step 4 — test_schema_parity 更新

- [ ] **Step 4.1: `EXPECTED_FIELDS["PlanGenerationPayload"] = {"evidence_pack_id", "transit_matrix"}` を追加**
- [ ] **Step 4.2: `_MODELS["PlanGenerationPayload"] = PlanGenerationPayload` を追加、import も**
- [ ] **Step 4.3: 走らせて確認**

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_schema_parity.py -v
```

Expected: 3 件 PASS

### Step 5 — 全テスト + 型チェック

- [ ] **Step 5.1: backend 全 unit テスト**

```bash
cd apps/api && .venv/bin/python -m pytest -m "not integration" -v
```

Expected: 既存 + 新規 全 PASS

- [ ] **Step 5.2: frontend 型チェック**

```bash
pnpm --filter shared-types build
pnpm --filter web exec tsc --noEmit
```

Expected: エラーなし

### Step 6 — コミット提案

対象ファイル:
- `docs/data-model.md`
- `packages/shared-types/src/index.ts`
- `apps/api/src/schemas/__init__.py`
- `apps/api/tests/test_schema_parity.py`

メッセージ案: `chore(phase-1.3c): PlanGenerationPayload を 3 点同期（UUID + max_length=200 required）`

---

## Task 2: Transit Validator 実装（TDD）

**Files:**
- Create: `apps/api/src/evidence/validator.py`
- Create: `apps/api/tests/test_evidence_validator.py`

### Red 段階

- [ ] **Step 1: 失敗テストを書く（Codex 指摘を全て網羅）**

```python
# apps/api/tests/test_evidence_validator.py
"""Transit Validator のユニットテスト（Phase 1.3c）。"""
from __future__ import annotations

from datetime import date

import pytest

from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    PlacePoint,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
    TransitEdge,
)
from src.evidence.validator import (
    HARD_CAP,
    MAX_EDGE_DISTANCE_KM,
    TransitMatrixValidationError,
    validate_client_transit_matrix,
)
from src.schemas import BudgetBreakdown, ClientTransitEdge


def _place(place_id: str, lat: float = 35.0, lng: float = 139.0) -> PlacePoint:
    return PlacePoint(
        place_id=place_id,
        name=f"p-{place_id}",
        category=[],
        lat=lat,
        lng=lng,
        address="addr",
        opening_hours=[],
        price_level=None,
        rating=None,
        user_ratings_total=None,
    )


def _pack(placemap: dict[str, tuple[float, float]] | list[str]) -> EvidencePack:
    """placemap は {id: (lat, lng)} か ["id1", "id2"] のどちらも受ける。"""
    if isinstance(placemap, list):
        points = [_place(pid) for pid in placemap]
    else:
        points = [_place(pid, lat, lng) for pid, (lat, lng) in placemap.items()]
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            departure_point="新宿",
            start_mode="auto",
            mode_payload=None,
            participants=[QueryContextParticipant(name="a", wishes="", tags=[])],
        ),
        places=points,
        transit_matrix=[],
        budget_constraints=BudgetConstraints(
            total_jpy_per_person=30000,
            breakdown_percent=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
            breakdown_jpy=BudgetBreakdownJPY(lodging=12000, meal=9000, activity=6000, transit=3000),
        ),
        temporal_constraints=TemporalConstraints(
            start_datetime="2026-06-01T09:00:00+09:00",
            end_datetime="2026-06-02T20:00:00+09:00",
            total_days=2,
        ),
    )


def _edge(
    a: str,
    b: str,
    mode: str = "train",
    duration_min: int = 30,
    route_summary: str = "JR",
) -> ClientTransitEdge:
    return ClientTransitEdge(
        from_place_id=a,
        to_place_id=b,
        mode=mode,
        route_summary=route_summary,
        duration_min=duration_min,
        fare_jpy=500,
        candidate_departures=["09:00"],
    )


# ==============================
# 基本
# ==============================


def test_happy_path_returns_transit_edges():
    pack = _pack(["A", "B", "C"])
    edges = [_edge("A", "B"), _edge("B", "A"), _edge("A", "C")]
    result = validate_client_transit_matrix(edges, pack)
    assert len(result) == 3
    assert all(isinstance(e, TransitEdge) for e in result)
    assert {(e.from_place_id, e.to_place_id) for e in result} == {
        ("A", "B"), ("B", "A"), ("A", "C")
    }


def test_empty_edges_is_allowed():
    pack = _pack(["A", "B"])
    assert validate_client_transit_matrix([], pack) == []


def test_single_place_allows_only_empty():
    pack = _pack(["A"])
    assert validate_client_transit_matrix([], pack) == []
    with pytest.raises(TransitMatrixValidationError):
        validate_client_transit_matrix([_edge("A", "A")], pack)


def test_returns_transit_edge_preserves_all_fields():
    pack = _pack(["A", "B"])
    edge = ClientTransitEdge(
        from_place_id="A",
        to_place_id="B",
        mode="bus",
        route_summary="高速バス",
        duration_min=90,
        fare_jpy=1800,
        candidate_departures=["09:00", "10:30"],
    )
    [out] = validate_client_transit_matrix([edge], pack)
    assert out.from_place_id == "A"
    assert out.to_place_id == "B"
    assert out.mode == "bus"
    assert out.route_summary == "高速バス"
    assert out.duration_min == 90
    assert out.fare_jpy == 1800
    assert out.candidate_departures == ["09:00", "10:30"]


# ==============================
# place_id 所属
# ==============================


def test_unknown_from_place_id_is_rejected():
    pack = _pack(["A", "B"])
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([_edge("Z", "B")], pack)
    assert "from_place_id" in str(exc.value)


def test_unknown_to_place_id_is_rejected():
    pack = _pack(["A", "B"])
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([_edge("A", "Z")], pack)
    assert "to_place_id" in str(exc.value)


# ==============================
# 自己ループ
# ==============================


def test_self_loop_is_rejected():
    pack = _pack(["A", "B"])
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([_edge("A", "A")], pack)
    assert "self" in str(exc.value).lower()


# ==============================
# 件数上限（hard cap と N*(N-1)）
# ==============================


def test_small_n_directed_edge_cap():
    # N=2, cap=min(HARD_CAP, 2*(2-1))=2
    pack = _pack(["A", "B"])
    edges = [
        _edge("A", "B", mode="train"),
        _edge("B", "A", mode="train"),
        _edge("A", "B", mode="bus"),
    ]
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix(edges, pack)
    assert "limit" in str(exc.value).lower() or "cap" in str(exc.value).lower()


def test_hard_cap_is_enforced_even_when_nn1_is_larger():
    """N が大きくて N*(N-1) >> HARD_CAP の場合、hard cap が効く。

    Codex re-review で偽陽性指摘あり（v2 の `i % len(ids)` 循環だと同じキーが
    重複生成され、cap 超過ではなく「矛盾重複」で落ちる穴があった）。
    このテストでは `(from, to, mode)` で完全に一意な有向ペアだけを列挙し、
    先頭から HARD_CAP+1 件を取ることで「cap 超過のみで落ちる」ことを保証する。
    """
    # N=15 → 有向ペア 15*14=210 > HARD_CAP=200。同一座標で距離制約を回避
    ids = [f"p{i}" for i in range(15)]
    pack = _pack({pid: (35.0, 139.0) for pid in ids})

    # 有向ペアを全列挙、(i, i) は除外
    all_pairs = [(i, j) for i in range(len(ids)) for j in range(len(ids)) if i != j]
    assert len(all_pairs) > HARD_CAP  # 事前アサート: 一意ペアで HARD_CAP を超えられる

    edges = [
        _edge(ids[i], ids[j], mode="train", route_summary=f"r-{i}-{j}")
        for (i, j) in all_pairs[: HARD_CAP + 1]
    ]
    # 各 (from, to, mode) が一意であることを確認（dedupe で捨てられて cap 判定を免れないこと）
    keys = {(e.from_place_id, e.to_place_id, e.mode) for e in edges}
    assert len(keys) == len(edges)

    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix(edges, pack)
    # "limit" / "cap" / "exceeds" のいずれかが含まれる（矛盾重複メッセージではない）
    msg = str(exc.value).lower()
    assert "cap" in msg or "limit" in msg or "exceeds" in msg
    assert "conflict" not in msg and "duplicate" not in msg  # 偽陽性検出ガード


def test_cap_is_evaluated_after_normalization():
    """完全一致重複の drop は cap 判定前に適用され、正規化後の件数で cap 比較する。"""
    # N=2, cap=2。完全一致 3 件送るが dedupe 後 1 件なので pass
    pack = _pack(["A", "B"])
    e = _edge("A", "B", mode="train")
    result = validate_client_transit_matrix([e, e, e], pack)
    assert len(result) == 1


# ==============================
# 距離上限
# ==============================


def test_distance_over_cap_is_rejected():
    # 東京(35.68, 139.69) と 大阪(34.70, 135.50) は ~400km
    pack = _pack({"T": (35.68, 139.69), "O": (34.70, 135.50)})
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([_edge("T", "O")], pack)
    assert "distance" in str(exc.value).lower() or "km" in str(exc.value).lower()


def test_distance_exactly_within_cap_is_allowed():
    # 2 点を 14.9km 離して置く（lat 差 ~0.134 度）
    pack = _pack({"A": (35.0, 139.0), "B": (35.134, 139.0)})
    result = validate_client_transit_matrix([_edge("A", "B")], pack)
    assert len(result) == 1


def test_same_coordinate_distance_zero_is_allowed():
    pack = _pack({"A": (35.0, 139.0), "B": (35.0, 139.0)})
    assert len(validate_client_transit_matrix([_edge("A", "B")], pack)) == 1


# ==============================
# 重複: 完全一致 drop / 矛盾 reject
# ==============================


def test_exact_duplicate_is_silently_dropped():
    pack = _pack(["A", "B", "C"])
    e1 = _edge("A", "B", mode="train", route_summary="JR", duration_min=30)
    e2 = _edge("A", "B", mode="train", route_summary="JR", duration_min=30)
    e3 = _edge("B", "A", mode="train")
    result = validate_client_transit_matrix([e1, e2, e3], pack)
    assert len(result) == 2
    ab = [r for r in result if (r.from_place_id, r.to_place_id) == ("A", "B")]
    assert len(ab) == 1


def test_conflicting_duplicate_is_rejected():
    """同じ (from,to,mode) で route_summary や duration_min が違うのは隠蔽リスク → reject。"""
    pack = _pack(["A", "B"])
    e1 = _edge("A", "B", mode="train", route_summary="JR", duration_min=30)
    e2 = _edge("A", "B", mode="train", route_summary="私鉄", duration_min=45)
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([e1, e2], pack)
    assert "conflict" in str(exc.value).lower() or "duplicate" in str(exc.value).lower()


def test_different_mode_same_pair_is_allowed():
    """(A,B,train) と (A,B,bus) は key が違うので両方保持。"""
    pack = _pack(["A", "B"])
    e1 = _edge("A", "B", mode="train")
    e2 = _edge("A", "B", mode="bus")
    result = validate_client_transit_matrix([e1, e2], pack)
    assert len(result) == 2
    assert {r.mode for r in result} == {"train", "bus"}


# ==============================
# 順序の安定性（デバッグ容易性）
# ==============================


def test_output_preserves_input_order():
    pack = _pack(["A", "B", "C"])
    edges = [_edge("B", "A"), _edge("A", "C"), _edge("A", "B")]
    result = validate_client_transit_matrix(edges, pack)
    pairs = [(r.from_place_id, r.to_place_id) for r in result]
    assert pairs == [("B", "A"), ("A", "C"), ("A", "B")]
```

- [ ] **Step 2: Red 確認**

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_evidence_validator.py -v
```

Expected: 全件 FAIL（ModuleNotFoundError）

### Green 段階

- [ ] **Step 3: validator.py を実装**

```python
# apps/api/src/evidence/validator.py
"""フロントが送る `ClientTransitEdge` を Evidence Pack と照合して検証する純関数。

Pydantic 層（`schemas.ClientTransitEdge`）で値域・文字長・HH:mm は既にガード済み。
`PlanGenerationPayload` の `max_length=200` で静的 hard cap もかかる。本モジュールは
以下の **文脈依存の検証** を担う:

1. from/to の place_id が Evidence Pack.places に含まれる
2. from == to（自己ループ）を拒否
3. 件数上限 min(HARD_CAP, N*(N-1)) を正規化後件数で判定（N = |pack.places|）
4. 距離上限（haversine）: MAX_EDGE_DISTANCE_KM 超は reject
5. (from, to, mode) 3-tuple 重複:
   - 完全一致（全フィールド値が等しい、`candidate_departures` は **順序を保持したリスト比較**）
     → silently drop
   - 矛盾（key 一致で他フィールド値が違う）→ reject（隠蔽リスク防止）
   - **注**: `candidate_departures` の要素集合が同じでも順序が違う場合は「矛盾」扱い。
     現状フロントは 1 要素固定なので顕在化しないが、将来複数化時に再検討する
     （順序に意味がない配列として扱うなら `frozenset` ベース比較に切り替える）

距離は haversine 公式で計算する。フロント transit.ts の haversineKm と同一アルゴリズム
（単体テストで挙動を固定）。将来共通定数を置くなら pack.py や共通 util に移す。
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from .pack import EvidencePack, PlacePoint, TransitEdge
from ..schemas import ClientTransitEdge

HARD_CAP: int = 200
"""transit_matrix に許容する有向エッジ数の絶対上限（N*(N-1) と比較して小さい方を採用）。"""

MAX_EDGE_DISTANCE_KM: float = 15.0
"""1 エッジの許容距離上限。フロント側は 10km フィルタだが、浮動小数点誤差と将来の余裕を込めて 15km。"""


class TransitMatrixValidationError(ValueError):
    """文脈依存の transit_matrix バリデーション失敗。ルート側は 400 に翻訳。"""


def _haversine_km(a: PlacePoint, b: PlacePoint) -> float:
    """同一の球体モデルでフロントと揃える（半径 6371km）。"""
    R = 6371.0
    dlat = radians(b.lat - a.lat)
    dlng = radians(b.lng - a.lng)
    lat1 = radians(a.lat)
    lat2 = radians(b.lat)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * R * asin(sqrt(h))


def _conflict(existing: ClientTransitEdge, incoming: ClientTransitEdge) -> bool:
    """完全一致なら False、矛盾なら True。key ((from,to,mode)) は既に一致している前提。"""
    return (
        existing.route_summary != incoming.route_summary
        or existing.duration_min != incoming.duration_min
        or existing.fare_jpy != incoming.fare_jpy
        or list(existing.candidate_departures) != list(incoming.candidate_departures)
    )


def validate_client_transit_matrix(
    edges: list[ClientTransitEdge],
    pack: EvidencePack,
) -> list[TransitEdge]:
    places_by_id: dict[str, PlacePoint] = {p.place_id: p for p in pack.places}
    n = len(places_by_id)

    normalized_order: list[ClientTransitEdge] = []
    seen_by_key: dict[tuple[str, str, str], ClientTransitEdge] = {}

    for e in edges:
        # 場所の所属
        if e.from_place_id not in places_by_id:
            raise TransitMatrixValidationError(
                f"unknown from_place_id: {e.from_place_id!r} is not in pack.places"
            )
        if e.to_place_id not in places_by_id:
            raise TransitMatrixValidationError(
                f"unknown to_place_id: {e.to_place_id!r} is not in pack.places"
            )
        # 自己ループ
        if e.from_place_id == e.to_place_id:
            raise TransitMatrixValidationError(
                f"self-loop edge is not allowed: {e.from_place_id}"
            )
        # 距離（place_id の所属が確認できてから座標参照）
        dist = _haversine_km(places_by_id[e.from_place_id], places_by_id[e.to_place_id])
        if dist > MAX_EDGE_DISTANCE_KM:
            raise TransitMatrixValidationError(
                f"edge distance {dist:.2f}km exceeds MAX_EDGE_DISTANCE_KM={MAX_EDGE_DISTANCE_KM} "
                f"({e.from_place_id} → {e.to_place_id})"
            )

        # 重複処理
        key = (e.from_place_id, e.to_place_id, e.mode)
        if key in seen_by_key:
            if _conflict(seen_by_key[key], e):
                raise TransitMatrixValidationError(
                    f"conflicting duplicate edge for {key}: "
                    f"existing and incoming disagree on attribute values"
                )
            # 完全一致 → silently drop
            continue
        seen_by_key[key] = e
        normalized_order.append(e)

    # 正規化後件数で cap 判定
    cap = min(HARD_CAP, n * (n - 1))
    if len(normalized_order) > cap:
        raise TransitMatrixValidationError(
            f"transit_matrix length {len(normalized_order)} after dedupe exceeds cap {cap} "
            f"(HARD_CAP={HARD_CAP}, |places|={n})"
        )

    return [
        TransitEdge(
            from_place_id=e.from_place_id,
            to_place_id=e.to_place_id,
            mode=e.mode,
            route_summary=e.route_summary,
            duration_min=e.duration_min,
            fare_jpy=e.fare_jpy,
            candidate_departures=list(e.candidate_departures),
        )
        for e in normalized_order
    ]
```

- [ ] **Step 4: Green 確認**

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_evidence_validator.py -v
```

Expected: 全件 PASS（16 件前後）

- [ ] **Step 5: コミット提案**

対象:
- `apps/api/src/evidence/validator.py`
- `apps/api/tests/test_evidence_validator.py`

メッセージ案: `feat(phase-1.3c): サーバー側 Transit Validator（place_id 所属 / 自己ループ / 距離 15km / hard cap 200 / 完全一致 drop・矛盾 reject）`

---

## Task 3: `/api/plans/generate` 骨組み（TDD）

**Files:**
- Create: `apps/api/src/routes/plan_routes.py`
- Create: `apps/api/tests/test_routes_plans.py`

### Red 段階

- [ ] **Step 1: ルートのユニットテストを書く（認証・入力・cache・validator・debug mode・500）**

```python
# apps/api/tests/test_routes_plans.py
"""POST /api/plans/generate のユニットテスト（mocked auth + cache + validator）。

Phase 1.3c では LLM 未接続。通常レスポンスは `{ plan_id: null }`。
`?debug=1` のときのみ `{ plan_id: null, evidence_pack: {...} }`。
"""
from __future__ import annotations

import os
from datetime import date
from uuid import uuid4
from unittest.mock import MagicMock, patch

import pytest

from src.app import create_app
from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    PlacePoint,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
)
from src.schemas import BudgetBreakdown


@pytest.fixture
def client():
    app = create_app()
    return app.test_client()


def _pack(place_ids: list[str]) -> EvidencePack:
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            departure_point="新宿",
            start_mode="auto",
            mode_payload=None,
            participants=[QueryContextParticipant(name="太郎", wishes="", tags=[])],
        ),
        places=[
            PlacePoint(
                place_id=pid,
                name=f"p-{pid}",
                category=[],
                lat=35.0,
                lng=139.0,
                address="addr",
                opening_hours=[],
                price_level=None,
                rating=None,
                user_ratings_total=None,
            )
            for pid in place_ids
        ],
        transit_matrix=[],
        budget_constraints=BudgetConstraints(
            total_jpy_per_person=30000,
            breakdown_percent=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
            breakdown_jpy=BudgetBreakdownJPY(lodging=12000, meal=9000, activity=6000, transit=3000),
        ),
        temporal_constraints=TemporalConstraints(
            start_datetime="2026-06-01T09:00:00+09:00",
            end_datetime="2026-06-02T20:00:00+09:00",
            total_days=2,
        ),
    )


def _mock_auth(session_id: str = "owner-xyz"):
    user = MagicMock(id=session_id)
    user_resp = MagicMock(user=user)
    instance = MagicMock()
    instance.auth.get_user.return_value = user_resp
    return instance


def _edge(a: str, b: str, mode: str = "train") -> dict:
    return {
        "from_place_id": a,
        "to_place_id": b,
        "mode": mode,
        "route_summary": "JR",
        "duration_min": 30,
        "fare_jpy": 500,
        "candidate_departures": ["09:00"],
    }


def _valid_body(pack_id: str | None = None, edges: list[dict] | None = None) -> dict:
    return {
        "evidence_pack_id": pack_id or str(uuid4()),
        "transit_matrix": edges if edges is not None else [_edge("A", "B"), _edge("B", "A")],
    }


# ==============================
# 認証
# ==============================


def test_missing_auth_returns_401(client):
    res = client.post("/api/plans/generate", json=_valid_body())
    assert res.status_code == 401


@patch("src.auth.get_supabase_client")
def test_invalid_jwt_returns_401(mock_auth_factory, client):
    instance = MagicMock()
    instance.auth.get_user.side_effect = Exception("expired")
    mock_auth_factory.return_value = instance
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer bad"},
    )
    assert res.status_code == 401


# ==============================
# 入力検証
# ==============================


@patch("src.auth.get_supabase_client")
def test_non_json_body_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    res = client.post(
        "/api/plans/generate",
        data="not json",
        content_type="text/plain",
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_non_object_json_body_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    res = client.post(
        "/api/plans/generate",
        json=["not", "a", "dict"],
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_invalid_uuid_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    body = _valid_body(pack_id="not-a-uuid")
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_too_many_edges_returns_400(mock_auth_factory, client):
    """Pydantic max_length=200 の静的 hard cap で弾かれる（先パース段階）。"""
    mock_auth_factory.return_value = _mock_auth()
    body = _valid_body(edges=[_edge("A", "B") for _ in range(201)])
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_validation_error_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    body = _valid_body()
    body["transit_matrix"][0]["candidate_departures"] = ["25:00"]  # HH:mm 違反
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400
    assert "validation" in res.get_json()["error"].lower()


# ==============================
# キャッシュ取得
# ==============================


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_expired_or_unknown_pack_returns_404(mock_auth_factory, mock_load, client):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = None
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 404


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_pack_is_loaded_with_owner_session_id(mock_auth_factory, mock_load, client):
    pack_id = str(uuid4())
    mock_auth_factory.return_value = _mock_auth(session_id="owner-zzz")
    mock_load.return_value = _pack(["A", "B"])
    client.post(
        "/api/plans/generate",
        json=_valid_body(pack_id),
        headers={"Authorization": "Bearer ok"},
    )
    args, kwargs = mock_load.call_args
    # load_pack(pack_id, owner_session_id=...)
    assert args[0] == pack_id
    assert kwargs["owner_session_id"] == "owner-zzz"


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_load_pack_db_error_returns_500(mock_auth_factory, mock_load, client):
    """load_pack が raise した場合は 500 に畳み込まれる（スタックは logger.exception）。"""
    mock_auth_factory.return_value = _mock_auth()
    mock_load.side_effect = RuntimeError("supabase is down")
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 500


# ==============================
# Validator 結合
# ==============================


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_unknown_place_id_in_transit_returns_400(mock_auth_factory, mock_load, client):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    body = _valid_body(edges=[_edge("A", "C")])
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


# ==============================
# 成功パス（通常 / debug）
# ==============================


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_happy_path_default_returns_only_plan_id_null(
    mock_auth_factory, mock_load, client
):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body == {"plan_id": None}  # evidence_pack は含まれない


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_happy_path_debug_mode_returns_merged_pack(
    mock_auth_factory, mock_load, client
):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    res = client.post(
        "/api/plans/generate?debug=1",
        json=_valid_body(edges=[_edge("A", "B"), _edge("B", "A")]),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["plan_id"] is None
    pack = payload["evidence_pack"]
    assert len(pack["transit_matrix"]) == 2
    keys = {(e["from_place_id"], e["to_place_id"]) for e in pack["transit_matrix"]}
    assert keys == {("A", "B"), ("B", "A")}
    assert {p["place_id"] for p in pack["places"]} == {"A", "B"}


# ==============================
# メソッド制約
# ==============================


def test_get_returns_405(client):
    res = client.get("/api/plans/generate")
    assert res.status_code == 405
```

- [ ] **Step 2: Red 確認**

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_routes_plans.py -v
```

Expected: 全件 FAIL（ImportError or 404）

### Green 段階

- [ ] **Step 3: app.py 更新（blueprint 登録 + MAX_CONTENT_LENGTH）**

```python
# apps/api/src/app.py の create_app() 内に追加
# Flask 既定値は None なので setdefault では効かない（Codex re-review High 指摘）。
# 直接代入することで確実に 413 レスポンスを返せる。
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024  # 256KB: transit_matrix 200 件を十分カバー

from .routes.plan_routes import bp as plan_bp
app.register_blueprint(plan_bp)
```

既存 `evidence_bp` の直下に配置。

- [ ] **Step 4: plan_routes.py を実装**

```python
# apps/api/src/routes/plan_routes.py
"""`/api/plans/*` エンドポイント（Phase 1.3c 時点では `/generate` の骨組みのみ）。

設計:
- JWT 認証必須（`require_session`）
- 入力 `PlanGenerationPayload` を Pydantic validate
  - evidence_pack_id: UUID 型
  - transit_matrix: list[ClientTransitEdge]、max_length=200（静的 hard cap）
- `load_pack(evidence_pack_id, owner_session_id=...)` で取り出し、None は 404
  （期限切れ / 未知 / 所有者不一致を集約、情報漏えい防止。内部ログにはステータスを残す）
- `validate_client_transit_matrix` で place_id 所属 / 自己ループ / 距離 15km /
  dedupe（完全一致 drop、矛盾 reject）/ 正規化後件数上限 を検証
- 検証済み transit を base_pack に merge（transit_matrix のみ上書き）
- 通常レスポンス: `{ "plan_id": null }`
- `?debug=1` の時のみ `{ "plan_id": null, "evidence_pack": <dict> }` を返す
  （1.3d で `{ "plan_id": <UUID> }` に差し替え予定）
"""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from ..auth import require_session
from ..evidence.cache import load_pack
from ..evidence.validator import (
    TransitMatrixValidationError,
    validate_client_transit_matrix,
)
from ..schemas import PlanGenerationPayload

bp = Blueprint("plan_routes", __name__, url_prefix="/api/plans")


@bp.post("/generate")
@require_session
def generate_plan():
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400

    try:
        payload = PlanGenerationPayload.model_validate(raw)
    except ValidationError as e:
        return jsonify({"error": "validation failed", "details": e.errors()}), 400

    pack = load_pack(str(payload.evidence_pack_id), owner_session_id=g.owner_session_id)
    if pack is None:
        # PII 対策: Supabase user.id と pack_id は生で残さず、hash 付きの短縮 prefix のみ
        # 記録する。運用時に特定のリクエストを追跡する場合は別途相関 ID を持たせる
        # （本スコープ外）。
        import hashlib
        owner_hash = hashlib.sha256(
            g.owner_session_id.encode("utf-8")
        ).hexdigest()[:8]
        pack_prefix = str(payload.evidence_pack_id)[:8]
        current_app.logger.info(
            f"generate_plan: pack not available (pack_prefix={pack_prefix} "
            f"owner_hash={owner_hash}, reason=expired|unknown|owner-mismatch)"
        )
        return jsonify({"error": "evidence pack not found or expired"}), 404

    try:
        validated = validate_client_transit_matrix(payload.transit_matrix, pack)
    except TransitMatrixValidationError as e:
        current_app.logger.info(f"transit_matrix rejected: {e}")
        return jsonify({"error": f"transit_matrix validation failed: {e}"}), 400

    merged = pack.model_copy(update={"transit_matrix": validated})

    # 1.3c のレスポンスは debug 用途を除いて {"plan_id": null} のみ。
    # ?debug=1 の時だけ merged pack を追加で返す。1.3d で LLM を繋いだら
    # 通常レスポンスを {"plan_id": <UUID>} に差し替える。
    if request.args.get("debug") == "1":
        return jsonify({
            "plan_id": None,
            "evidence_pack": merged.model_dump(mode="json"),
        }), 200
    return jsonify({"plan_id": None}), 200
```

- [ ] **Step 5: Green 確認**

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_routes_plans.py -v
```

Expected: 全件 PASS（15 件前後）

- [ ] **Step 6: 全ユニットテスト確認**

```bash
cd apps/api && .venv/bin/python -m pytest -m "not integration" -v
```

Expected: 既存 + 追加分が全 PASS

- [ ] **Step 7: コミット提案**

対象:
- `apps/api/src/routes/plan_routes.py`
- `apps/api/src/app.py`
- `apps/api/tests/test_routes_plans.py`

メッセージ案: `feat(phase-1.3c): POST /api/plans/generate 骨組み（認証 / Pydantic / Transit Validator / ?debug=1 で merged pack 返却）`

---

## Task 4: Integration テスト（live Supabase）

**Files:**
- Modify: `apps/api/tests/test_routes_plans.py`（末尾に追加）

- [ ] **Step 1: helper と integration テストを追加**

```python
def _has_full_stack() -> bool:
    return all(
        os.environ.get(k) for k in (
            "GOOGLE_MAPS_API_KEY",
            "NEXT_PUBLIC_SUPABASE_URL",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        )
    ) and len(os.environ.get("GOOGLE_MAPS_API_KEY", "")) > 20


def _places_request_body() -> dict:
    return {
        "title": "箱根温泉旅",
        "region": "箱根",
        "start_date": "2026-06-01",
        "end_date": "2026-06-02",
        "departure_point": "新宿駅",
        "budget_per_person_jpy": 30000,
        "budget_breakdown": {"lodging": 40, "meal": 30, "activity": 20, "transit": 10},
        "start_mode": "auto",
        "mode_payload": None,
        "participants": [
            {
                "display_name": "太郎",
                "avatar_color": "#D97757",
                "wishes_text": "ゆったり温泉",
                "tags": ["温泉"],
                "order_index": 0,
            },
        ],
    }


@pytest.mark.integration
@pytest.mark.skipif(not _has_full_stack(), reason="full stack env keys not set")
def test_integration_evidence_to_generate_round_trip(client):
    """1.3a で取得した evidence_pack_id に対して 1.3c (?debug=1) を叩き、merged pack が返ることを確認。

    transit_matrix はフロント SDK を使わず、1.3a の places から手動で組んだ 2 件のみ。
    """
    from supabase import create_client

    anon_client = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    sign_in = anon_client.auth.sign_in_anonymously()
    jwt_token = sign_in.session.access_token
    user_id = sign_in.user.id

    try:
        res = client.post(
            "/api/evidence/places",
            json=_places_request_body(),
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        places_body = res.get_json()
        pack_id = places_body["evidence_pack_id"]
        assert len(places_body["places"]) >= 2
        a = places_body["places"][0]["place_id"]
        b = places_body["places"][1]["place_id"]

        # 距離が 15km 超で弾かれると integration 成功判定が崩れる。Places の結果から
        # 15km 以内のペアを能動的に探して採用する。見つからなければ明確に fail させる
        # （skip で distance 以外の不具合まで隠さない: Codex re-review Medium 指摘）。
        from math import asin, cos, radians, sin, sqrt

        def _km(p, q):
            R = 6371.0
            dlat = radians(q["lat"] - p["lat"])
            dlng = radians(q["lng"] - p["lng"])
            h = (
                sin(dlat / 2) ** 2
                + cos(radians(p["lat"])) * cos(radians(q["lat"])) * sin(dlng / 2) ** 2
            )
            return 2 * R * asin(sqrt(h))

        chosen_pair = None
        for i, p in enumerate(places_body["places"]):
            for q in places_body["places"][i + 1 :]:
                if _km(p, q) <= 14.0:  # 15km 上限の内側にマージン
                    chosen_pair = (p, q)
                    break
            if chosen_pair:
                break
        assert chosen_pair is not None, (
            "Integration test requires at least one pair within 14km in 箱根 area; "
            "Places search returned only distant spots."
        )
        a = chosen_pair[0]["place_id"]
        b = chosen_pair[1]["place_id"]

        body = {
            "evidence_pack_id": pack_id,
            "transit_matrix": [_edge(a, b), _edge(b, a)],
        }
        # debug モードで merged pack を確認
        res2 = client.post(
            "/api/plans/generate?debug=1",
            json=body,
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res2.status_code == 200, res2.get_data(as_text=True)
        payload = res2.get_json()
        assert payload["plan_id"] is None
        assert len(payload["evidence_pack"]["transit_matrix"]) == 2
    finally:
        from src.supabase_client import get_supabase_client
        try:
            get_supabase_client().auth.admin.delete_user(user_id)
        except Exception:
            pass
```

- [ ] **Step 2: Integration テスト手動 run**

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_routes_plans.py -m integration -v
```

Expected: 1 件 PASS（箱根エリアの近距離スポットが選ばれた場合）

- [ ] **Step 3: コミット提案**

対象:
- `apps/api/tests/test_routes_plans.py`

メッセージ案: `test(phase-1.3c): /api/evidence/places → /api/plans/generate 統合テスト（live Supabase、?debug=1）`

---

## Task 5: todo.md 更新 + 最終コミット

**Files:**
- Modify: `tasks/todo.md`

- [ ] **Step 1: 1.3c セクションのチェックボックスを更新**

全ステップを `- [x]` にして、ヘッダを `#### 1.3c: ... ✅ 完了（develop: <hash>）` の形にする。

- [ ] **Step 2: コミット提案**

対象:
- `tasks/todo.md`

メッセージ案: `chore(phase-1.3c): todo.md を完了ステータスに更新`

---

## 自己レビュー（Self-Review、v2）

### Codex Must-fix への対応
1. DoS 対策 → `max_length=200` + `MAX_CONTENT_LENGTH=256KB` + `min(HARD_CAP, N*(N-1))` の 3 重 ✅
2. 型ドリフト → `transit_matrix` を required に、`evidence_pack_id` を `UUID` 型に ✅
3. dedupe → 完全一致 drop、矛盾 reject、cap は正規化後で判定 ✅
4. 距離上限 → `MAX_EDGE_DISTANCE_KM=15.0` をサーバー側で再検証 ✅
5. テスト穴 → `test_load_pack_db_error_returns_500` / `test_non_object_json_body_returns_400` / `test_too_many_edges_returns_400` / `test_invalid_uuid_returns_400` / dedupe 系 3 件追加 ✅
6. 3 点同期順序 → Task 1 を `docs → shared-types → Pydantic → parity` の順に修正 ✅

### Codex Nice-to-have への対応
1. debug opt-in → `?debug=1` で実装 ✅
2. 404 内部ログに reason（`logger.info` で "expired / unknown / owner-mismatch" を残す）✅
3. RFC7807 は既存の 404/400 の形式踏襲（1.3d 以降で統一したければ別タスク）→ スコープ外でもよい
4. Task 並列化 → Task2/3 は独立、Task 1 は先に。Task 4/5 は Task 3 終了後

### Codex v2 re-review への対応（v3 差分）
- **High-1** `MAX_CONTENT_LENGTH` の `setdefault` → 直接代入 ✅
- **High-2** hard cap テスト偽陽性 → `all_pairs` で一意性保証 + 「矛盾メッセージでないこと」を追加アサート ✅
- **Medium-3** ログ PII → `hashlib.sha256(...).hexdigest()[:8]` と pack_id の先頭 8 文字だけに限定 ✅
- **Medium-4** integration の 400 skip → 距離 14km 以内のペアを能動的に探索し、見つからなければ assert で fail ✅
- **Medium-5** `candidate_departures` 順序差分の扱い → validator docstring に明文化 ✅

### 型一貫性チェック
- `ClientTransitEdge`（schemas、API 入力）/ `TransitEdge`（evidence.pack、内部）で役割分担 ✅
- `PlanGenerationPayload.evidence_pack_id: UUID` を `load_pack(str(...))` で文字列に落とす（既存 cache API が str 前提）✅
- `EvidencePack.transit_matrix: list[TransitEdge]` に validator の返値をそのまま突っ込める ✅

### 1.3d への橋渡し
- デフォルトレスポンスが `{ plan_id: null }` なのでフロントは「null なら失敗扱い」で実装すれば 1.3d で `{ plan_id: <UUID> }` への差し替えが無痛
- debug mode は shared-types に含まれないので 1.3d で消してもフロント型が壊れない
- Transit Validator は純関数で merged pack を返すので、1.3d でも呼び出しだけ残して LLM を足せば良い

---

## 実装フロー（ユーザ承認後）

1. **この計画書を再度 Codex に見せ、v2 として re-review を依頼**（v1 → v2 の差分で潰せたか確認）
2. ユーザから Go サイン
3. `feat/plan-generation-skeleton` ブランチを `develop` から切って Task 1 → 5 を順に実行
4. 各 Task のコミット提案（メッセージ案 + 対象ファイル一覧）をユーザに渡す
5. 全 Task 完了後、**実装差分**を Codex にレビュー依頼
6. 必要なら修正してコミット提案を追加
7. ユーザが `develop` にマージ
