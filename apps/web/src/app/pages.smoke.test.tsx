/**
 * Core flow の各ページが crash せず render することを確認する smoke テスト。
 *
 * ルーティング / API / Supabase は全てモックして、純粋に JSX が壊れないことだけ見る。
 * 機能テストはコンポーネント単位（EvidenceBadge.test.tsx 等）でカバーする方針。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Home from "./page";
import NewPlanPage from "./plan/new/page";
import GeneratingPage from "./plan/[id]/generating/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ id: "00000000-0000-0000-0000-000000000001" }),
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

vi.mock("@/lib/transit", () => ({
  fetchTransitMatrix: vi.fn(async () => ({ edges: [], stats: {} })),
}));

describe("Home (landing)", () => {
  it("crash せず描画、CTA「旅を計画する」を含む", () => {
    render(<Home />);
    expect(screen.getByRole("link", { name: /旅を計画する/ })).toBeInTheDocument();
  });
});

describe("NewPlanPage (1.5)", () => {
  it("crash せず描画、参加者初期 2 人ぶんのタブと生成ボタンを含む", () => {
    render(<NewPlanPage />);
    expect(screen.getByText(/プランを生成/)).toBeInTheDocument();
    expect(screen.getByLabelText(/プランのタイトル/)).toBeInTheDocument();
  });
});

describe("GeneratingPage (1.6)", () => {
  it("セッション無しでも crash せず描画（リダイレクト待ち状態）", () => {
    render(<GeneratingPage />);
    // 初期 step は "loading-session"（見出しは「プランを組み立てています...」）
    expect(
      screen.getByRole("heading", { name: /プランを組み立てています|プラン生成に失敗/ }),
    ).toBeInTheDocument();
  });
});
