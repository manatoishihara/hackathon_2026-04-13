import { z } from "zod";
import type { GeneratePlanRequest } from "shared-types";

/**
 * 1.5 希望入力画面のフォーム用 zod スキーマ。
 * `GeneratePlanRequest`（shared-types）と 1:1 対応する構造で書く。
 *
 * shared-types は正典、ここは RHF 向けの実行時バリデーション。フィールド追加・削除は
 * `docs/data-model.md` 更新 → shared-types 更新 → ここの同期、という順で行う
 * （zod と shared-types の手動同期、Codex 指摘の Nice-to-have ドリフト検出は将来課題）。
 */

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

export const planFormSchema = z
  .object({
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
    start_mode: z.enum(["auto", "anchor", "theme"]),
    mode_payload: z.record(z.string(), z.unknown()).nullable(),
    participants: z
      .array(participantInputSchema)
      .min(2, "参加者は 2 人以上必要です")
      .max(5, "参加者は 5 人までです"),
  })
  .refine(
    (d) => d.start_date <= d.end_date,
    { message: "開始日は終了日より前に指定してください", path: ["end_date"] },
  );

export type PlanFormValues = z.infer<typeof planFormSchema>;

/**
 * RHF + zod の `PlanFormValues` は `GeneratePlanRequest` と構造的に互換であることを型で保証する。
 * 将来 shared-types 側が変わったとき、この行の型エラーで気付ける（Nice-to-have ドリフト検出の代替）。
 */
const _typeCheck: GeneratePlanRequest = {} as PlanFormValues;
void _typeCheck;

export type ParticipantFormInput = z.infer<typeof participantInputSchema>;
