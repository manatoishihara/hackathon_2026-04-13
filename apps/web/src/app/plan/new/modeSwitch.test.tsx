/**
 * Phase 2.1 出発モード切替の `/plan/new` 統合テスト（Codex Major 1 対応）。
 *
 * `discriminatedUnion + RHF + setValue 2 段更新` の肝である `handleModeChange`
 * がページ統合時に正しく動くことを担保する。コンポーネント単体テストでは見えない
 * 「mode 切替時に sub UI が出入りする」「mode_payload エラーが残らない」を検証する。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NewPlanPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/supabase", () => ({
  ensureAnonymousSession: vi.fn(async () => "mock-jwt"),
  getCurrentUserId: vi.fn(async () => "mock-user"),
  getSupabaseAccessToken: vi.fn(async () => "mock-jwt"),
  getSupabaseClient: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  postEvidencePlaces: vi.fn(),
  postPlanGenerate: vi.fn(),
  createPlanAndParticipants: vi.fn(),
  updatePlanStatus: vi.fn(),
  checkApiHealth: vi.fn(async () => true),
}));

describe("/plan/new mode 切替統合", () => {
  it("初期状態は auto モードで、AnchorPicker は表示されない", () => {
    render(<NewPlanPage />);
    const autoRadio = screen.getByLabelText(/お任せ/) as HTMLInputElement;
    expect(autoRadio.checked).toBe(true);
    expect(screen.queryByLabelText(/スポット検索/)).not.toBeInTheDocument();
  });

  it("こだわりモード選択で AnchorPicker が現れ、auto に戻すと消える", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/こだわり/));
    expect(screen.getByLabelText(/スポット検索/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/お任せ/));
    expect(screen.queryByLabelText(/スポット検索/)).not.toBeInTheDocument();
  });

  it("auto → こだわり 切替で AnchorPicker は empty state（mode_payload リセット）", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/こだわり/));
    expect(screen.getByTestId("anchor-empty-state")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/お任せ/));
    expect(screen.queryByTestId("anchor-empty-state")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/こだわり/));
    expect(screen.getByTestId("anchor-empty-state")).toBeInTheDocument();
  });
});
