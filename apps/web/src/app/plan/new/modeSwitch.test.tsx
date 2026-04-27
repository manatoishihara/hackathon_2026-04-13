/**
 * Phase 2.1 出発モード切替の `/plan/new` 統合テスト（Codex Major 1 対応）。
 *
 * `discriminatedUnion + RHF + setValue 2 段更新` の肝である
 * `handleModeChange` / `handleThemeChange(null→auto)` がページ統合時に
 * 正しく動くことを担保する。コンポーネント単体テストでは見えない
 * 「mode 切替時に sub UI が出入りする」「mode_payload エラーが残らない」
 * 「auto 復帰 safety」を検証する。
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
  it("初期状態は auto モードで、AnchorPicker / ThemePicker は表示されない", () => {
    render(<NewPlanPage />);
    // ModeSelector の auto radio が checked
    const autoRadio = screen.getByLabelText(/お任せ/) as HTMLInputElement;
    expect(autoRadio.checked).toBe(true);
    // sub UI は非表示
    expect(screen.queryByLabelText(/スポット検索/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "温泉" })).not.toBeInTheDocument();
  });

  it("anchor モード選択で AnchorPicker が現れ、auto に戻すと消える", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/アンカー/));
    expect(screen.getByLabelText(/スポット検索/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "温泉" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/お任せ/));
    expect(screen.queryByLabelText(/スポット検索/)).not.toBeInTheDocument();
  });

  it("theme モード選択で ThemePicker が現れ、anchor に切替えると ThemePicker が消えて AnchorPicker が出る", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/テーマ/));
    expect(screen.getByRole("button", { name: "温泉" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/スポット検索/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/アンカー/));
    expect(screen.queryByRole("button", { name: "温泉" })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/スポット検索/)).toBeInTheDocument();
  });

  it("theme モードで現選択 chip を再クリックすると auto に戻る（解除 safety）", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/テーマ/));
    // デフォルト onsen が選択中
    const onsenChip = screen.getByRole("button", { name: "温泉" });
    expect(onsenChip).toHaveAttribute("aria-pressed", "true");
    // 再クリックで解除 → ThemePicker そのものが消えて auto に戻る
    fireEvent.click(onsenChip);
    expect(screen.queryByRole("button", { name: "温泉" })).not.toBeInTheDocument();
    const autoRadio = screen.getByLabelText(/お任せ/) as HTMLInputElement;
    expect(autoRadio.checked).toBe(true);
  });

  it("anchor → theme → anchor 往復で AnchorPicker は empty state（mode_payload リセット）", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/アンカー/));
    // empty state placeholder が表示されている（chip は無い）
    expect(screen.getByTestId("anchor-empty-state")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/テーマ/));
    expect(screen.queryByTestId("anchor-empty-state")).not.toBeInTheDocument();

    // anchor に戻ると mode_payload が空配列でリセットされ、empty state に戻る
    fireEvent.click(screen.getByLabelText(/アンカー/));
    expect(screen.getByTestId("anchor-empty-state")).toBeInTheDocument();
  });
});
