# Data Model

このドキュメントは**正典**。データ構造の変更はまずここを更新し、その後に実装を修正せよ。

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
  share_token TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_plans_session_id ON plans(session_id);
CREATE INDEX idx_plans_share_token ON plans(share_token);

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
-- Row Level Security
-- ==============================
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_items ENABLE ROW LEVEL SECURITY;

-- 自分のセッションのみアクセス可
CREATE POLICY "Own session only" ON sessions
  FOR ALL USING (id = auth.uid());

CREATE POLICY "Plans of own session" ON plans
  FOR ALL USING (session_id = auth.uid());

CREATE POLICY "Participants of own plans" ON participants
  FOR ALL USING (plan_id IN (SELECT id FROM plans WHERE session_id = auth.uid()));

CREATE POLICY "PlanItems of own plans" ON plan_items
  FOR ALL USING (plan_id IN (SELECT id FROM plans WHERE session_id = auth.uid()));

-- 共有トークン経由の読み取りは別途 View で提供
CREATE VIEW shared_plans AS
  SELECT p.*, pa.*, pi.*
  FROM plans p
  LEFT JOIN participants pa ON pa.plan_id = p.id
  LEFT JOIN plan_items pi ON pi.plan_id = p.id
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
```

## Pydantic 対応（`apps/api/src/schemas/`）

上記 TypeScript 型と一対一で対応する Pydantic v2 スキーマを配置せよ。フィールド名、nullability、enum を完全に一致させること。型が不整合だとフロントが壊れる。

## Phase 1.3 で追加予定の型（API 分割に伴う）

日本国内の transit は Google のサーバー API から取れないため、プラン生成を 2 段に
分ける（詳細は `docs/evidence-pack.md` / `docs/architecture.md` / `tasks/lessons.md`）。

**この「計画節」は 3 点同期の対象外**（`.claude/rules/data-model-sync.md` の「計画節の
扱い」参照）。擬似コードで意図だけ示し、Phase 1.3 の実装着手時に shared-types /
Pydantic / test_schema_parity への実コード追加 + 3 点同期を一括で行う。

```typescript
// POST /api/evidence/places リクエスト
// → 現在の GeneratePlanRequest をそのまま流用する予定（フィールドは同一）

// POST /api/evidence/places レスポンス
export type EvidencePlacesResponse = {
  evidence_pack_id: string;       // サーバー短期キャッシュへの参照（TTL 15 分想定）
  places: Array<{
    place_id: string;
    name: string;
    lat: number;
    lng: number;
  }>;
  // 注: フロントは Maps JS DirectionsService 呼び出しに必要な最小サブセットのみ受け取る。
  // 予算・時間制約・参加者情報などはサーバー側の短期キャッシュに保持する。
};

// POST /api/plans/generate リクエスト
export type PlanGenerationPayload = {
  evidence_pack_id: string;
  transit_matrix: ClientTransitEdge[];
};

export type ClientTransitEdge = {
  from_place_id: string;     // EvidencePack.places に含まれる ID に限る（サーバーで検証）
  to_place_id: string;
  mode: 'train' | 'bus' | 'walk' | 'car';
  route_summary: string;     // 120 文字以内
  duration_min: number;      // 0〜1440
  fare_jpy: number | null;   // 0〜500000
  candidate_departures: string[]; // HH:mm、1〜10 要素
};

// POST /api/plans/generate レスポンス
// → 現在の GeneratePlanResponse ({ plan_id }) を流用
```

**未決事項**: `candidate_departures` の単数/複数化、`route_summary` のサーバー側 rewrite 要否、
`evidence_pack_id` のストア（Supabase vs in-memory vs Redis）は Phase 1.3 着手時に確定させる。
