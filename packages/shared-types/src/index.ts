/**
 * Routeful 共通型定義（正典: docs/data-model.md）。
 *
 * 変更手順:
 *   1. docs/data-model.md を先に更新
 *   2. 本ファイルを同期
 *   3. apps/api/src/schemas.py も合わせて同期
 *   4. apps/api/tests/test_schema_parity.py のクロスチェックが通ることを確認
 */

// ==============================
// 列挙型
// ==============================

export type StartMode = "auto" | "anchor" | "theme";
export type ItemType = "activity" | "meal" | "transit" | "lodging";
export type CostConfidence = "verified" | "estimated" | "unknown";
export type TransitMode = "train" | "bus" | "walk" | "car";
export type PlanStatus = "draft" | "generating" | "succeeded" | "failed";

// Phase 2.1 出発モード切替: テーマ key の単一情報源（runtime + 型両方で参照可能）。
// バックエンドの `apps/api/src/themes.py` の THEME_REGISTRY と同期して運用する
// （ThemeKey 値の追加 / 改名は両方を必ず揃える）。
export const THEME_KEYS = [
  "onsen",
  "art",
  "gourmet",
  "nature",
  "history",
  "experience",
] as const;
export type ThemeKey = (typeof THEME_KEYS)[number];

// 日本語ラベル（UI 表示 + LLM プロンプトの `mode_context_md` で参照される）。
// 値はバックエンド `themes.py` の THEME_REGISTRY[*].label と同期。
export const THEME_LABELS_JP: Record<ThemeKey, string> = {
  onsen: "温泉",
  art: "アート",
  gourmet: "グルメ",
  nature: "自然",
  history: "歴史",
  experience: "体験",
};

// Phase 2.1: start_mode 別 mode_payload 内訳。
// DB の plans.mode_payload は JSONB のまま（Plan 型は Record<string, unknown> | null
// で後方互換）、新規 form / API request 経路では下記 helper 型で narrow する。
export type AnchorModePayload = {
  // 必ずプランに含めたい Google Places place_id（1〜3 件、サーバ側で範囲 validate）
  anchor_place_ids: string[];
};

export type ThemeModePayload = {
  theme: ThemeKey;
};

// ==============================
// 構造体（entities）
// ==============================

export type BudgetBreakdown = {
  lodging: number;
  meal: number;
  activity: number;
  transit: number;
};

export type Plan = {
  id: string;
  session_id: string;
  title: string;
  region: string;
  start_date: string; // ISO date (YYYY-MM-DD)
  end_date: string;
  departure_point: string;
  budget_per_person_jpy: number;
  budget_breakdown: BudgetBreakdown;
  start_mode: StartMode;
  mode_payload: Record<string, unknown> | null;
  status: PlanStatus;
  share_token: string | null;
  created_at: string; // ISO datetime
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
  price_range_jpy?: { start: number; end: number }; // Phase 3 polish 第 9 段、Google Places priceRange の JPY 換算
  external_url?: string; // Phase 3 polish 第 9 段、楽天トラベル等の外部詳細ページ URL
  verified_at?: string; // ISO datetime
  sources: string[]; // ["Google Places", "楽天トラベル"]
};

export type TransitToNext = {
  mode: TransitMode;
  route: string;
  departure_time: string; // "HH:mm"
  duration_min: number;
  fare_jpy: number | null;
  polyline: string | null;
};

export type PlanItem = {
  id: string;
  plan_id: string;
  order_index: number;
  item_type: ItemType;
  title: string;
  description: string | null;
  start_time: string; // ISO datetime
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
// API リクエスト / レスポンス
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
  participants: Omit<Participant, "id" | "plan_id">[];
};

export type GeneratePlanResponse = {
  plan_id: string;
};

export type RegenerateItemRequest = {
  constraint?: string;
};

export type RegenerateItemResponse = {
  item: PlanItem;
};

// POST /api/evidence/places レスポンス（Phase 1.3a）。
// DirectionsService 呼び出しに必要な最小サブセットのみ返す。
// Evidence Pack 本体はサーバー短期キャッシュ（evidence_pack_sessions テーブル）。
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

// フロント Maps JS SDK の DirectionsService で取得した transit を
// `/api/plans/generate`（Phase 1.3c）に送る際のエッジ表現（Phase 1.3b で追加）。
// 有向エッジ: A→B と B→A は別レコード。サーバー側は Pydantic Field 制約で
// 値域・文字長・HH:mm 形式を検証し、place_id 所属 / 自己ループ / 距離 15km /
// dedupe は evidence/validator.py で実施する（Phase 1.3c）。
export type ClientTransitEdge = {
  from_place_id: string;
  to_place_id: string;
  mode: "train" | "bus" | "walk" | "car";
  route_summary: string; // 1〜120 文字
  duration_min: number; // 0〜1440
  fare_jpy: number | null; // 0〜500000
  candidate_departures: string[]; // HH:mm 形式、1〜10 要素
};

// POST /api/plans/generate リクエスト（Phase 1.3c で実型化、1.3c+ で plan_id 追加）。
// plan_id はフロント（/plan/new submit 時）が crypto.randomUUID() で発行、
// 同時に plans テーブルに INSERT 済みの UUID。1.3d で owner 検証と plan_items 保存に使う。
// evidence_pack_id はサーバー短期キャッシュ (evidence_pack_sessions.id) の UUID。
// transit_matrix の要素制約は ClientTransitEdge（Phase 1.3b）。サーバー側は
// 件数最大 200、距離 15km 以内、place_id 所属、矛盾重複禁止で検証する。
export type PlanGenerationPayload = {
  plan_id: string;
  evidence_pack_id: string;
  transit_matrix: ClientTransitEdge[];
};

// POST /api/plans/:id/share レスポンス（Phase 1.9 DB-4）。
// 既存 share_token があれば再生成せず同一値を返す。
// share_url はサーバーで URL を組み立てて返す（フロントで hard-code しない）。
export type ShareResponse = {
  share_token: string;
  share_url: string;
};

// GET /api/plans/shared/:token レスポンス（Phase 1.9 DB-5）。
// Flask + service role で RLS を跨いで読む（tasks/handoff-db.md の方針）。
// 公開レスポンスには session_id / share_token / plan_id を含めない（識別子漏洩防止）。
export type SharedPlanSummary = Omit<Plan, "session_id" | "share_token">;
export type SharedParticipant = Omit<Participant, "plan_id">;
export type SharedPlanItem = Omit<PlanItem, "plan_id">;

export type SharedPlanResponse = {
  plan: SharedPlanSummary;
  participants: SharedParticipant[];
  plan_items: SharedPlanItem[];
};

// ==============================
// UI ヘルパー（Phase 1.7 の Evidence バッジ表示用）
// ==============================

export type EvidenceBadgeVariant = "verified" | "estimated" | "unknown";

export type EvidenceBadgeInfo = {
  variant: EvidenceBadgeVariant;
  label: string; // 画面に出す短い日本語ラベル
  colorToken: string; // globals.css の CSS custom property 名
};

/**
 * CostConfidence + sources から表示バッジ情報を算出する純粋関数。
 * 絵文字は使わず、アイコンはフロント側の Phosphor コンポーネントで表現する想定。
 */
export function getEvidenceBadgeInfo(
  confidence: CostConfidence,
  sources: readonly string[],
): EvidenceBadgeInfo {
  // Phase 2 polish v6 fix (2026-04-28): cost_confidence は **コスト推定の確度** であり、
  // **place の検証状態** とは別軸。Google Places で検証済みの place でも price_level
  // 未設定なら cost_confidence=unknown になり旧実装は「不明」badge を出していた。
  // sources が非空 = 何らかの検証済データあり、と判定して以下優先度で表示:
  //   1. cost_confidence=verified (確実なコスト) → verified badge with source
  //   2. cost_confidence=estimated (推定コスト) → estimated badge
  //   3. cost_confidence=unknown だが sources あり → verified badge (place は検証済み、
  //      コストだけ不明と分かる UX、demo の 「Google Places verified」表示)
  //   4. cost_confidence=unknown かつ sources 空 → 不明 badge
  if (confidence === "verified") {
    return {
      variant: "verified",
      label: sources[0] ?? "検証済み",
      colorToken: "--color-evidence-verified",
    };
  }
  if (confidence === "estimated") {
    return {
      variant: "estimated",
      label: "推定",
      colorToken: "--color-evidence-estimated",
    };
  }
  // confidence === "unknown" だが place が検証済 (sources あり) なら verified 寄り表示
  if (sources.length > 0) {
    return {
      variant: "verified",
      label: sources[0],
      colorToken: "--color-evidence-verified",
    };
  }
  return {
    variant: "unknown",
    label: "不明",
    colorToken: "--color-evidence-unknown",
  };
}

// ==============================
// Runtime バリデーションヘルパー
// ==============================

/**
 * BudgetBreakdown が合計 100 (%) で各フィールドが [0, 100] に収まっているか検証。
 * フロントのスライダー UI と LLM プロンプトに渡す前の両方で使う。
 */
export function isValidBudgetBreakdown(b: BudgetBreakdown): boolean {
  const values = [b.lodging, b.meal, b.activity, b.transit];
  if (values.some((v) => v < 0 || v > 100 || !Number.isFinite(v))) {
    return false;
  }
  return values.reduce((a, c) => a + c, 0) === 100;
}

/**
 * 参加者の人数制約チェック（2〜5 人）。Phase 1.5 の希望入力で使う。
 */
export function isValidParticipantCount(n: number): boolean {
  return Number.isInteger(n) && n >= 2 && n <= 5;
}
