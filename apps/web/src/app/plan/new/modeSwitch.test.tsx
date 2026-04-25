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
}));

describe("/plan/new mode 切替統合", () => {
  it("初期状態は auto モードで、AnchorPicker / ThemePicker は表示されない", () => {
    render(<NewPlanPage />);
    // ModeSelector の auto radio が checked
    const autoRadio = screen.getByLabelText(/お任せ/) as HTMLInputElement;
    expect(autoRadio.checked).toBe(true);
    // sub UI は非表示
    expect(screen.queryByLabelText("place_id")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "温泉" })).not.toBeInTheDocument();
  });

  it("anchor モード選択で AnchorPicker が現れ、auto に戻すと消える", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/アンカー/));
    expect(screen.getByLabelText("place_id")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "温泉" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/お任せ/));
    expect(screen.queryByLabelText("place_id")).not.toBeInTheDocument();
  });

  it("theme モード選択で ThemePicker が現れ、anchor に切替えると ThemePicker が消えて AnchorPicker が出る", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/テーマ/));
    expect(screen.getByRole("button", { name: "温泉" })).toBeInTheDocument();
    expect(screen.queryByLabelText("place_id")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/アンカー/));
    expect(screen.queryByRole("button", { name: "温泉" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("place_id")).toBeInTheDocument();
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

  it("anchor で chip を追加し、theme に切替えると anchor 状態は破棄される", () => {
    render(<NewPlanPage />);
    fireEvent.click(screen.getByLabelText(/アンカー/));
    const input = screen.getByLabelText("place_id") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ChIJ_test" } });
    fireEvent.click(screen.getByRole("button", { name: "追加" }));
    expect(screen.getByText("ChIJ_test")).toBeInTheDocument();

    // theme に切替
    fireEvent.click(screen.getByLabelText(/テーマ/));
    expect(screen.queryByText("ChIJ_test")).not.toBeInTheDocument();
    // anchor に戻したら空配列で再開（前の入力は残らない）
    fireEvent.click(screen.getByLabelText(/アンカー/));
    expect(screen.queryByText("ChIJ_test")).not.toBeInTheDocument();
  });
});
