# Data Model

このドキュメントはデータ構造の**概念モデル + TS/Pydantic 型の正典**。

**SQL DDL の正典は `supabase/migrations/` 配下の連番ファイル**（2026-04-25 以降）。
本ドキュメントの「PostgreSQL DDL」節は migrations ファイルのスナップショット（最新状態）を貼っているだけで、変更は migrations に新しい連番ファイルを追加する形で行う。
既存 DDL を移植した本番 Supabase には migrations 20260401_00 / 20260419_01 / 20260424_02 / 20260424_03 / 20260424_04 が適用済み（冪等設計なので再適用しても安全）。

## 概念モデル

```
Session (匿名) ──┬── Plan ──┬── Participant (2〜5人)
                 │          │
                 │          └── PlanItem (時系列)
                 │                 ├── Location (Place 参照)
                 │                 ├── Evidence
                 │                 └── TransitToNext
                 │
                 └── ShareToken（閲覧専用の共有用）
```

## PostgreSQL DDL（Supabase SQL Editor に貼り付けて実行）

```sql
-- ==============================
-- Sessions（匿名セッション）
-- ==============================
CREATE TABLE sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==============================
-- Plans（旅行プラン全体）
-- ==============================
CREATE TABLE plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  region TEXT NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  departure_point TEXT NOT NULL,
  budget_per_person_jpy INTEGER NOT NULL,
  budget_breakdown JSONB NOT NULL, -- {lodging: 40, meal: 30, activity: 20, transit: 10}
  start_mode TEXT NOT NULL CHECK (start_mode IN ('auto', 'anchor', 'theme')),
  mode_payload JSONB, -- anchor型なら ["place_id1", "place_id2"], theme型なら {"theme": "onsen"}
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'generating', 'succeeded', 'failed')),
  share_token TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_plans_session_id ON plans(session_id);
CREATE INDEX idx_plans_share_token ON plans(share_token);
CREATE INDEX idx_plans_status ON plans(status);

-- ==============================
-- Participants（参加者 2〜5人）
-- ==============================
CREATE TABLE participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  display_name TEXT NOT NULL,
  avatar_color TEXT NOT NULL, -- HEX
  wishes_text TEXT NOT NULL, -- 自由記述
  tags TEXT[] DEFAULT '{}', -- ["温泉", "和食", "ゆったり派"]
  order_index INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_participants_plan_id ON participants(plan_id);

-- ==============================
-- PlanItems（プランの各アイテム、時系列）
-- ==============================
CREATE TABLE plan_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  order_index INTEGER NOT NULL, -- プラン内の並び順

  -- 基本情報
  item_type TEXT NOT NULL CHECK (item_type IN ('activity', 'meal', 'transit', 'lodging')),
  title TEXT NOT NULL,
  description TEXT,
  start_time TIMESTAMPTZ NOT NULL,
  end_time TIMESTAMPTZ NOT NULL,

  -- 場所
  place_id TEXT, -- Google Places ID（transit の場合は NULL）
  place_name TEXT,
  lat DOUBLE PRECISION,
  lng DOUBLE PRECISION,
  address TEXT,

  -- コスト
  cost_jpy INTEGER, -- 参加者1人あたり
  cost_confidence TEXT CHECK (cost_confidence IN ('verified', 'estimated', 'unknown')),

  -- Evidence（根拠）
  evidence JSONB NOT NULL,

  -- 次のアイテムへの交通（activity → meal の間など）
  transit_to_next JSONB, -- {mode, route, departure_time, duration_min, fare_jpy, polyline}

  -- メモ
  notes TEXT,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_plan_items_plan_id ON plan_items(plan_id);
CREATE INDEX idx_plan_items_order ON plan_items(plan_id, order_index);

-- ==============================
-- EvidencePackSessions（/api/evidence/places の短期キャッシュ、Phase 1.3a）
-- ==============================
-- フロントが /api/evidence/places で取得した evidence_pack_id を
-- /api/plans/generate へ送るまでの間 Pack 本体を保持する。
-- owner_session_id でバインドし、他人の pack_id を再利用できないようにする。
-- 期限切れレコードは store_pack の opportunistic cleanup で都度削除。
CREATE TABLE evidence_pack_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_session_id UUID NOT NULL,
  pack JSONB NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '15 minutes'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_evidence_pack_sessions_expires_at
  ON evidence_pack_sessions(expires_at);
CREATE INDEX idx_evidence_pack_sessions_owner
  ON evidence_pack_sessions(owner_session_id);

-- ==============================
-- Row Level Security
-- ==============================
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_pack_sessions ENABLE ROW LEVEL SECURITY;
-- evidence_pack_sessions はポリシー無し = anon 完全遮断、service_role のみ操作可

-- 自分のセッションのみアクセス可
CREATE POLICY "Own session only" ON sessions
  FOR ALL USING (id = auth.uid());

CREATE POLICY "Plans of own session" ON plans
  FOR ALL USING (session_id = auth.uid());

CREATE POLICY "Participants of own plans" ON participants
  FOR ALL USING (plan_id IN (SELECT id FROM plans WHERE session_id = auth.uid()));

CREATE POLICY "PlanItems of own plans" ON plan_items
  FOR ALL USING (plan_id IN (SELECT id FROM plans WHERE session_id = auth.uid()));

-- 共有トークン経由の読み取り用 view（Phase 1.9 の実装は Flask + service_role 経由を
-- 採用したため、view 利用は optional）。
-- plans / participants / plan_items を単一行に flatten しない（カラム名衝突するため）。
CREATE OR REPLACE VIEW shared_plans AS
  SELECT p.*
  FROM plans p
  WHERE p.share_token IS NOT NULL;
```

## TypeScript 型定義（`packages/shared-types/src/index.ts`）

```typescript
// ==============================
// 基本型
// ==============================
export type BudgetBreakdown = {
  lodging: number;   // 0-100 (合計 100)
  meal: number;
  activity: number;
  transit: number;
};

export type StartMode = 'auto' | 'anchor' | 'theme';

export type ItemType = 'activity' | 'meal' | 'transit' | 'lodging';

export type CostConfidence = 'verified' | 'estimated' | 'unknown';

export type PlanStatus = 'draft' | 'generating' | 'succeeded' | 'failed';

// Phase 2 polish (2026-04-27): 移動手段指定。
// - all_modes: フォールバック chain (TRANSIT → WALKING / DRIVING) で経路探索（既存挙動）
// - public_transit_only: 車利用不可シナリオで DRIVING を経路から除外
// Plan には保存しない（DB / RPC 列追加スコープ外）。GeneratePlanRequest と内部 QueryContext
// にだけ載せ、Pack 経由で LLM プロンプトと transit fetch にだけ届ける。
export type TransportMode = 'all_modes' | 'public_transit_only';

// Phase 2.1 出発モード切替で使う theme key（テーマモードの選択肢）
export type ThemeKey =
  | 'onsen'
  | 'art'
  | 'gourmet'
  | 'nature'
  | 'history'
  | 'experience';

// Phase 2.1: start_mode に応じた mode_payload 内訳（discriminated by start_mode）。
// DB 側は plans.mode_payload JSONB なので Plan 自体の型は Record<string, unknown> | null
// のまま（後方互換のため緩い）。新規生成リクエスト / フロント form では以下の helper 型で
// 強く validate する。
export type AnchorModePayload = {
  // 必ずプランに含めたい Google Places place_id（1〜3 件）
  anchor_place_ids: string[];
};

export type ThemeModePayload = {
  theme: ThemeKey;
};

// AutoModePayload は null（追加データなし）。Union 表現上は省略可。

// ==============================
// エンティティ
// ==============================
export type Plan = {
  id: string;
  session_id: string;
  title: string;
  region: string;
  start_date: string; // ISO date
  end_date: string;
  departure_point: string;
  budget_per_person_jpy: number;
  budget_breakdown: BudgetBreakdown;
  start_mode: StartMode;
  mode_payload: Record<string, unknown> | null;
  status: PlanStatus;
  share_token: string | null;
  created_at: string;
  updated_at: string;
};

export type Participant = {
  id: string;
  plan_id: string;
  display_name: string;
  avatar_color: string;
  wishes_text: string;
  tags: string[];
  order_index: number;
};

export type Location = {
  place_id: string | null;
  place_name: string | null;
  lat: number | null;
  lng: number | null;
  address: string | null;
};

export type Evidence = {
  opening_hours?: string;
  rating?: number;
  price_level?: number; // 1-4
  verified_at?: string; // ISO datetime
  sources: string[]; // ["Google Places", "楽天トラベル"]
};

export type TransitToNext = {
  mode: 'train' | 'bus' | 'walk' | 'car';
  route: string; // "JR山手線 渋谷→新宿"
  departure_time: string; // "13:15"
  duration_min: number;
  fare_jpy: number | null;
  polyline: string | null; // encoded polyline
};

export type PlanItem = {
  id: string;
  plan_id: string;
  order_index: number;
  item_type: ItemType;
  title: string;
  description: string | null;
  start_time: string;
  end_time: string;
  location: Location;
  cost_jpy: number | null;
  cost_confidence: CostConfidence;
  evidence: Evidence;
  transit_to_next: TransitToNext | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

// ==============================
// API リクエスト/レスポンス
// ==============================
export type GeneratePlanRequest = {
  title: string;
  region: string;
  start_date: string;
  end_date: string;
  departure_point: string;
  budget_per_person_jpy: number;
  budget_breakdown: BudgetBreakdown;
  start_mode: StartMode;
  mode_payload: Record<string, unknown> | null;
  // Phase 2 polish: 移動手段指定。デフォルトは 'all_modes'（既存挙動）
  transport_mode: TransportMode;
  participants: Omit<Participant, 'id' | 'plan_id'>[];
};

export type GeneratePlanResponse = {
  plan_id: string;
};

export type RegenerateItemRequest = {
  constraint?: string; // "もっと静かな場所で" 等
};

export type RegenerateItemResponse = {
  item: PlanItem;
};

// POST /api/evidence/places レスポンス (Phase 1.3a)
// リクエストは GeneratePlanRequest をそのまま使う。レスポンスは
// Maps JS DirectionsService を呼ぶのに必要な最小サブセットのみ返す。
// 予算・時間制約・参加者情報はサーバー短期キャッシュに格納し、
// /api/plans/generate 呼び出し時に evidence_pack_id でサーバーが取り出す。
export type EvidencePlacesPlaceSummary = {
  place_id: string;
  name: string;
  lat: number;
  lng: number;
};

export type EvidencePlacesResponse = {
  evidence_pack_id: string;
  places: EvidencePlacesPlaceSummary[];
};

// フロント Maps JS SDK で取得した transit を Phase 1.3c の
// /api/plans/generate に送る際の 1 要素（Phase 1.3b で昇格）。
// 有向エッジ: A→B と B→A は別レコード。サーバー側は Pydantic Field 制約と
// place_id 所属検証（Phase 1.3c）でバリデートする。
export type ClientTransitEdge = {
  from_place_id: string;     // EvidencePack.places に含まれる ID に限る（サーバーで検証）
  to_place_id: string;
  mode: 'train' | 'bus' | 'walk' | 'car';
  route_summary: string;     // 1〜120 文字
  duration_min: number;      // 0〜1440
  fare_jpy: number | null;   // 0〜500000
  candidate_departures: string[]; // HH:mm 形式、1〜10 要素
};

// POST /api/plans/generate リクエスト（Phase 1.3c で実型化、1.3c+ で plan_id 追加）。
// plan_id はフロントが発行して plans テーブルに INSERT 済みの UUID（1.5 submit 時に発行）。
// evidence_pack_id はサーバー短期キャッシュ (evidence_pack_sessions.id) の UUID。
// transit_matrix の要素制約は ClientTransitEdge（Phase 1.3b）。サーバー側は
// 件数最大 200（hard cap、フロント実装は 40 前後）、距離 15km 以内、place_id 所属、
// 矛盾重複禁止で検証する（`apps/api/src/evidence/validator.py`）。
// 1.3d では plan_id の owner 検証 + plan_items INSERT に使う。
export type PlanGenerationPayload = {
  plan_id: string; // UUID 文字列（フロント発行、plans テーブルに存在済み）
  evidence_pack_id: string; // UUID 文字列
  transit_matrix: ClientTransitEdge[];
};

// POST /api/plans/:id/share レスポンス（Phase 1.9 DB-4）。
// 既存 share_token があれば再生成せず同一値を返す（実装側でハンドリング）。
// share_url はサーバーで URL を組み立てて返す（フロントで hard-code しない）。
export type ShareResponse = {
  share_token: string;
  share_url: string;
};

// GET /api/plans/shared/:token レスポンス（Phase 1.9 DB-5）。
// Flask + service role で RLS を跨いで読み、クエリ側で share_token 一致必須 + NULL 除外
// を Flask のコードで強制する（handoff-db.md の方針）。
// 公開レスポンスには session_id / share_token / plan_id を含めない（識別子漏洩防止）。
// plan / participants / plan_items の 3 つ組を返して、フロントは通常 Plan と同じ
// レンダリングロジックで処理できる（欠損フィールドはフロントで補う設計）。
export type SharedPlanSummary = Omit<Plan, 'session_id' | 'share_token'>;
export type SharedParticipant = Omit<Participant, 'plan_id'>;
export type SharedPlanItem = Omit<PlanItem, 'plan_id'>;

export type SharedPlanResponse = {
  plan: SharedPlanSummary;
  participants: SharedParticipant[];
  plan_items: SharedPlanItem[];
};
```

## Pydantic 対応（`apps/api/src/schemas/`）

上記 TypeScript 型と一対一で対応する Pydantic v2 スキーマを配置せよ。フィールド名、nullability、enum を完全に一致させること。型が不整合だとフロントが壊れる。

## Phase 1.3 関連の実コード化履歴

日本国内の transit は Google のサーバー API から取れないため、プラン生成を 2 段に
分けた（詳細は `docs/evidence-pack.md` / `docs/architecture.md` / `tasks/lessons.md`）。

以下の型は Phase 1.3 で順次実コード化され、全て「API リクエスト/レスポンス」セクション
に統合済み:

- `EvidencePlacesPlaceSummary` / `EvidencePlacesResponse` — Phase 1.3a
- `ClientTransitEdge` — Phase 1.3b
- `PlanGenerationPayload` — Phase 1.3c

**未決事項の解消メモ（Phase 1.3c 時点）**:
- `candidate_departures`: 1〜10 要素の配列で継続（複数化対応済み、フロントは 1 要素固定）
- `route_summary`: サーバー側 rewrite は不要と判断（フロントが Google の vehicle.line 名を
  直接採用し、Pydantic の max_length=120 でカット）
- `evidence_pack_id` のストア: Supabase の `evidence_pack_sessions` テーブル（TTL 15 分）で確定
