import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PlanItem } from "./PlanItem";
import { mockPlanItems } from "@/lib/mocks/planItems";

describe("PlanItem (Phase 2.5 Evidence modal 統合)", () => {
  it("バッジクリックで Evidence モーダルが開き、title が表示される", async () => {
    const user = userEvent.setup();
    const item = mockPlanItems[1]; // 箱根彫刻の森美術館 (place_id あり)
    render(<PlanItem item={item} />);

    // 初期状態は modal なし
    expect(screen.queryByRole("dialog")).toBeNull();

    // バッジは button 化されているはず
    const badge = screen.getByRole("button", { name: /箱根彫刻の森美術館/ });
    await user.click(badge);

    // Modal が開き、title が含まれる
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/箱根彫刻の森美術館/)).toBeInTheDocument();
  });

  it("Modal を閉じると dialog が消える", async () => {
    const user = userEvent.setup();
    render(<PlanItem item={mockPlanItems[1]} />);

    await user.click(screen.getByRole("button", { name: /箱根彫刻の森美術館/ }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: /閉じる/ }));
    // findByRole は一度 mount された要素を待つが、queryByRole で消えたか確認
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("place_id が null の transit アイテムでも Modal が開く（Maps リンクは非表示）", async () => {
    const user = userEvent.setup();
    const transit = mockPlanItems[0]; // 新宿駅 → 箱根湯本駅 (place_id null)
    render(<PlanItem item={transit} />);

    const badge = screen.getByRole("button", { name: /新宿駅/ });
    await user.click(badge);

    const dialog = await screen.findByRole("dialog");
    // title は表示される
    expect(within(dialog).getByText(/新宿駅 → 箱根湯本駅/)).toBeInTheDocument();
    // Maps リンクは出ない
    expect(within(dialog).queryByRole("link", { name: /Google Maps/ })).toBeNull();
  });
});

describe("PlanItem 複数並列での独立開閉", () => {
  it("PlanItem 2 件を並べたとき、片方の modal を開いてももう片方には影響しない", async () => {
    const user = userEvent.setup();
    const item1 = mockPlanItems[1]; // 箱根彫刻の森美術館
    const item2 = mockPlanItems[2]; // 次の activity

    render(
      <>
        <PlanItem item={item1} />
        <PlanItem item={item2} />
      </>,
    );

    // item1 のバッジを開く
    const item1Badge = screen.getByRole("button", { name: new RegExp(item1.title) });
    await user.click(item1Badge);

    // item1 の dialog のみ開いている
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(new RegExp(item1.title))).toBeInTheDocument();

    // 閉じる
    await user.click(screen.getByRole("button", { name: /閉じる/ }));
    expect(screen.queryByRole("dialog")).toBeNull();

    // item2 の方を開く
    const item2Badge = screen.getByRole("button", { name: new RegExp(item2.title) });
    await user.click(item2Badge);

    const dialog2 = await screen.findByRole("dialog");
    expect(within(dialog2).getByText(new RegExp(item2.title))).toBeInTheDocument();
  });
});
