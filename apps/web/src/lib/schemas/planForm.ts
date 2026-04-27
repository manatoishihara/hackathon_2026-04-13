import { z } from "zod";
import { THEME_KEYS, type GeneratePlanRequest, type TransportMode } from "shared-types";

// Phase 2 polish (2026-04-27): TransportMode の値リストを単一情報源化。
// shared-types の TransportMode union と integrity を保つ（Codex Major 2 と同パターン）。
export const TRANSPORT_MODES = ["all_modes", "public_transit_only"] as const;
// 静的 type-check で shared-types の TransportMode と zip 整合する。
const _transportTypeCheck: TransportMode = TRANSPORT_MODES[0];
void _transportTypeCheck;
export const TRANSPORT_MODE_LABELS_JP: Record<TransportMode, string> = {
  all_modes: "車も使う",
  public_transit_only: "公共交通機関のみ",
};
// 注: schema 側 `.default()` を使うと z.infer の output 型に undefined が混じる
// （zod 4 系の挙動）ため、default は form の `DEFAULT_VALUES` 側で吸収する。
// バックエンド Pydantic 側にも `transport_mode: TransportMode = "all_modes"` を持たせて
// 古い API クライアントからの未送信 payload も既存挙動相当で受理する。
export const transportModeSchema = z.enum(TRANSPORT_MODES);

/**
 * 1.5 希望入力画面のフォーム用 zod スキーマ。
 * `GeneratePlanRequest`（shared-types）と 1:1 対応する構造で書く。
 *
 * shared-types は正典、ここは RHF 向けの実行時バリデーション。フィールド追加・削除は
 * `docs/data-model.md` 更新 → shared-types 更新 → ここの同期、という順で行う
 * （zod と shared-types の手動同期、Codex 指摘の Nice-to-have ドリフト検出は将来課題）。
 *
 * Phase 2.1: 出発モード切替で start_mode と mode_payload を discriminated union 化。
 * バックエンド `GeneratePlanRequest._validate_mode_payload_against_start_mode` と
 * 同等の整合検証を form 層でも行う（user 入力ミスを送信前に拾う）。
 */

// shared-types の THEME_KEYS を単一情報源として z.enum に流す（Codex Major 2 対応）。
// theme 追加 / 改名は shared-types/src/index.ts と apps/api/src/themes.py の両方を更新する。
export const themeKeySchema = z.enum(THEME_KEYS);
export type ThemeKey = z.infer<typeof themeKeySchema>;

export const anchorModePayloadSchema = z.object({
  anchor_place_ids: z
    .array(z.string().min(1, "place_id を入力").max(255, "place_id が長すぎます"))
    .min(1, "アンカーは 1 件以上必要です")
    .max(3, "アンカーは最大 3 件まで"),
});
export type AnchorModePayloadForm = z.infer<typeof anchorModePayloadSchema>;

export const themeModePayloadSchema = z.object({
  theme: themeKeySchema,
});
export type ThemeModePayloadForm = z.infer<typeof themeModePayloadSchema>;

export const participantInputSchema = z.object({
  display_name: z.string().min(1, "名前を入力してください").max(30, "30 文字以内で入力してください"),
  avatar_color: z.string().regex(/^#[0-9a-fA-F]{6}$/, "HEX カラー（#RRGGBB）で指定"),
  wishes_text: z.string().min(1, "希望を入力してください").max(500, "500 文字以内で入力してください"),
  tags: z.array(z.string().min(1).max(20)).max(10, "タグは 10 個までです"),
  order_index: z.number().int().min(0),
});

export const budgetBreakdownSchema = z
  .object({
    lodging: z.number().int().min(0).max(100),
    meal: z.number().int().min(0).max(100),
    activity: z.number().int().min(0).max(100),
    transit: z.number().int().min(0).max(100),
  })
  .refine(
    (b) => b.lodging + b.meal + b.activity + b.transit === 100,
    { message: "配分の合計が 100% になるように調整してください" },
  );

// 旅の基本情報 + 予算 + 参加者: 全 mode 共通の base fields
const baseFormFields = {
  title: z.string().min(1, "タイトルを入力してください").max(60),
  region: z.string().min(1, "行き先エリアを入力してください"),
  start_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "YYYY-MM-DD 形式で入力"),
  end_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "YYYY-MM-DD 形式で入力"),
  departure_point: z.string().min(1, "出発地を入力してください"),
  budget_per_person_jpy: z
    .number()
    .int()
    .min(1000, "1人あたり 1,000 円以上で指定してください")
    .max(1_000_000, "1人あたり 1,000,000 円以下で指定してください"),
  budget_breakdown: budgetBreakdownSchema,
  // Phase 2 polish (2026-04-27): 移動手段指定。default 'all_modes' で既存挙動と互換。
  transport_mode: transportModeSchema,
  participants: z
    .array(participantInputSchema)
    .min(2, "参加者は 2 人以上必要です")
    .max(5, "参加者は 5 人までです"),
};

const dateOrderRefinement = (
  d: { start_date: string; end_date: string },
): boolean => d.start_date <= d.end_date;

const dateOrderError = {
  message: "開始日は終了日より前に指定してください",
  path: ["end_date"],
};

// 各 mode variant: base fields + start_mode + mode_payload
const autoVariant = z
  .object({
    ...baseFormFields,
    start_mode: z.literal("auto"),
    mode_payload: z.null(),
  })
  .refine(dateOrderRefinement, dateOrderError);

const anchorVariant = z
  .object({
    ...baseFormFields,
    start_mode: z.literal("anchor"),
    mode_payload: anchorModePayloadSchema,
  })
  .refine(dateOrderRefinement, dateOrderError);

const themeVariant = z
  .object({
    ...baseFormFields,
    start_mode: z.literal("theme"),
    mode_payload: themeModePayloadSchema,
  })
  .refine(dateOrderRefinement, dateOrderError);

export const planFormSchema = z.discriminatedUnion("start_mode", [
  autoVariant,
  anchorVariant,
  themeVariant,
]);

export type PlanFormValues = z.infer<typeof planFormSchema>;

/**
 * RHF + zod の `PlanFormValues` は `GeneratePlanRequest` と構造的に互換であることを型で保証する。
 * 将来 shared-types 側が変わったとき、この行の型エラーで気付ける（Nice-to-have ドリフト検出の代替）。
 */
const _typeCheck: GeneratePlanRequest = {} as PlanFormValues;
void _typeCheck;

export type ParticipantFormInput = z.infer<typeof participantInputSchema>;
