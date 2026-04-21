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
