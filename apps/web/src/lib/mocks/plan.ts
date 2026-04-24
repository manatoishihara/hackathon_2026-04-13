import type { Plan } from "shared-types";

/**
 * モック Plan（箱根 1 泊 2 日）。`NEXT_PUBLIC_USE_MOCKS=1` 時に `getPlan` が返す。
 * デザイナーが 1.7 の見た目を確認するためだけのデータ、本番には流れない。
 */
export const mockPlan: Plan = {
  id: "00000000-0000-0000-0000-000000000001",
  session_id: "00000000-0000-0000-0000-000000000001",
  title: "箱根で温泉と自然を満喫する 2 日間",
  region: "箱根",
  start_date: "2026-06-01",
  end_date: "2026-06-02",
  departure_point: "新宿駅",
  budget_per_person_jpy: 30000,
  budget_breakdown: { lodging: 40, meal: 30, activity: 20, transit: 10 },
  start_mode: "auto",
  mode_payload: null,
  status: "succeeded",
  share_token: null,
  created_at: "2026-05-30T12:00:00+09:00",
  updated_at: "2026-05-30T12:30:00+09:00",
};
