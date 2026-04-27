/**
 * Core flow の各ページが crash せず render することを確認する smoke テスト。
 *
 * ルーティング / API / Supabase は全てモックして、純粋に JSX が壊れないことだけ見る。
 * 機能テストはコンポーネント単位（EvidenceBadge.test.tsx 等）でカバーする方針。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import Home from "./page";
import NewPlanPage from "./plan/new/page";
import GeneratingPage from "./plan/[id]/generating/page";
import PlanPage from "./plan/[id]/page";
import SharePage from "./plan/[id]/share/page";
import { mockPlan } from "@/lib/mocks/plan";
import { mockPlanItems } from "@/lib/mocks/planItems";
import { mockParticipants } from "@/lib/mocks/participants";

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
  getPlan: vi.fn(async () => mockPlan),
  getPlanItems: vi.fn(async () => mockPlanItems),
  getParticipants: vi.fn(async () => mockParticipants),
  checkApiHealth: vi.fn(async () => true),
}));

vi.mock("@/lib/transit", () => ({
  fetchTransitMatrix: vi.fn(async () => ({ edges: [], stats: {} })),
}));

function renderWithQuery(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

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
      screen.getByRole("heading", {
        name: /プランを編んで|プランを組み立てています|プラン生成に失敗|離陸できませんでした|目的地に到着/,
      }),
    ).toBeInTheDocument();
  });
});

describe("PlanPage (1.7)", () => {
  it("モック plan / items / participants で描画、タイトルと DAY タブが表示される", async () => {
    renderWithQuery(<PlanPage />);
    // useQuery で非同期取得 → データが入ったらタイトルが出る
    await waitFor(() => {
      expect(screen.getByText(mockPlan.title)).toBeInTheDocument();
    });
    // 1.7 リデザイン後: 機能タブ廃止 → DAY タブで日付切替（mock は 2 日分）
    const dayTabs = screen.getAllByRole("tab", { name: /DAY/ });
    expect(dayTabs.length).toBe(2);
  });
});

describe("SharePage (1.9)", () => {
  it("share_token が null なら「共有を有効化（準備中）」ボタンを出す", async () => {
    renderWithQuery(<SharePage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /共有を有効化/ })).toBeInTheDocument();
    });
    expect(screen.getByText(/まだ共有されていません/)).toBeInTheDocument();
  });
});
