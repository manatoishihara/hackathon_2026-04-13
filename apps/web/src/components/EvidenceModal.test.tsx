import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PlanItem } from "shared-types";

import { EvidenceModal } from "./EvidenceModal";

function makeItem(overrides: Partial<PlanItem> = {}): PlanItem {
  return {
    id: "item-1",
    plan_id: "plan-1",
    order_index: 0,
    item_type: "activity",
    title: "大涌谷",
    description: "硫黄香る箱根の名所",
    start_time: "2026-05-15T10:00:00+09:00",
    end_time: "2026-05-15T11:30:00+09:00",
    location: {
      place_id: "ChIJxxx",
      place_name: "大涌谷",
      lat: 35.244,
      lng: 139.018,
      address: "神奈川県箱根町",
    },
    cost_jpy: 1500,
    cost_confidence: "verified",
    evidence: {
      opening_hours: "09:00–17:00",
      rating: 4.5,
      price_level: 2,
      verified_at: "2026-04-26T01:32:00Z",
      sources: ["Google Places"],
    },
    transit_to_next: null,
    notes: null,
    created_at: "2026-04-26T00:00:00Z",
    updated_at: "2026-04-26T00:00:00Z",
    ...overrides,
  };
}

describe("EvidenceModal", () => {
  it("open=true で 5 フィールドと title が描画される", () => {
    render(
      <EvidenceModal item={makeItem()} open={true} onOpenChange={() => {}} />,
    );
    // Title
    expect(screen.getByText(/大涌谷/)).toBeInTheDocument();
    // 5 fields
    expect(screen.getByText("09:00–17:00")).toBeInTheDocument();
    expect(screen.getByText(/4\.5/)).toBeInTheDocument();
    expect(screen.getByText(/¥¥/)).toBeInTheDocument(); // price_level=2 → ¥¥
    expect(screen.getByText("Google Places")).toBeInTheDocument();
    expect(screen.getByText("2026-04-26 10:32")).toBeInTheDocument();
  });

  it("open=false なら描画されない", () => {
    render(
      <EvidenceModal item={makeItem()} open={false} onOpenChange={() => {}} />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opening_hours が undefined なら「— 不明」", () => {
    const item = makeItem({
      evidence: {
        rating: 4.5,
        price_level: 2,
        verified_at: "2026-04-26T01:32:00Z",
        sources: ["Google Places"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    // 営業時間 行に — 不明 が出る（label "営業時間" 行を探す）
    const hoursLabel = screen.getByText("営業時間");
    const row = hoursLabel.parentElement;
    expect(row?.textContent).toContain("— 不明");
  });

  it("rating が undefined なら評価行が「— 不明」", () => {
    const item = makeItem({
      evidence: {
        opening_hours: "09:00–17:00",
        price_level: 2,
        verified_at: "2026-04-26T01:32:00Z",
        sources: ["Google Places"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const ratingLabel = screen.getByText("評価");
    expect(ratingLabel.parentElement?.textContent).toContain("— 不明");
  });

  it("price_level / cost_jpy 両方無いなら価格帯行が「— 不明」", () => {
    const item = makeItem({
      cost_jpy: null,
      cost_confidence: "unknown",
      evidence: {
        opening_hours: "09:00–17:00",
        rating: 4.5,
        verified_at: "2026-04-26T01:32:00Z",
        sources: ["Google Places"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const priceLabel = screen.getByText("価格帯");
    expect(priceLabel.parentElement?.textContent).toContain("— 不明");
  });

  it("price_level 無しでも cost_jpy が estimated なら「￥X,XXX (推定)」表示 (Phase 3 polish 案 D 第 4 段)", () => {
    const item = makeItem({
      cost_jpy: 15000,
      cost_confidence: "estimated",
      evidence: {
        opening_hours: "09:00–17:00",
        rating: 4.5,
        verified_at: "2026-04-26T01:32:00Z",
        sources: ["楽天トラベル"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const priceLabel = screen.getByText("価格帯");
    const text = priceLabel.parentElement?.textContent ?? "";
    // formatJpy は Intl.NumberFormat ja-JP で全角 ￥ 記号
    expect(text).toContain("15,000");
    expect(text).toContain("(推定)");
  });

  it("price_level 無しで cost_confidence=verified なら「￥X,XXX」(タグ無し) で表示", () => {
    const item = makeItem({
      cost_jpy: 8000,
      cost_confidence: "verified",
      evidence: {
        opening_hours: "09:00–17:00",
        rating: 4.5,
        verified_at: "2026-04-26T01:32:00Z",
        sources: ["楽天トラベル"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const priceLabel = screen.getByText("価格帯");
    const text = priceLabel.parentElement?.textContent ?? "";
    expect(text).toContain("8,000");
    expect(text).not.toContain("(推定)");
  });

  it("verified_at が undefined なら検証日時行が「— 不明」", () => {
    const item = makeItem({
      evidence: {
        opening_hours: "09:00–17:00",
        rating: 4.5,
        price_level: 2,
        sources: ["Google Places"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const verifiedLabel = screen.getByText("検証日時");
    expect(verifiedLabel.parentElement?.textContent).toContain("— 不明");
  });

  it("sources が空配列なら出典行が「— 不明」", () => {
    const item = makeItem({
      evidence: {
        opening_hours: "09:00–17:00",
        rating: 4.5,
        price_level: 2,
        verified_at: "2026-04-26T01:32:00Z",
        sources: [],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const sourcesLabel = screen.getByText("出典");
    expect(sourcesLabel.parentElement?.textContent).toContain("— 不明");
  });

  it("price_level=4 なら ¥¥¥¥（4 枚）", () => {
    const item = makeItem({
      evidence: {
        opening_hours: "09:00–17:00",
        rating: 4.5,
        price_level: 4,
        verified_at: "2026-04-26T01:32:00Z",
        sources: ["Google Places"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    expect(screen.getByText("¥¥¥¥")).toBeInTheDocument();
  });

  // Phase 3 polish 第 9 段 Modal 配線 fix (2026-04-28): Google Places (New) の
  // priceRange を最優先で表示。¥¥¥ 記号より具体的な「¥1,500〜¥3,000」表記。
  it("price_range_jpy が start ≠ end なら「￥X,XXX〜￥Y,YYY」レンジ表示", () => {
    const item = makeItem({
      evidence: {
        price_range_jpy: { start: 1500, end: 3000 },
        price_level: 3, // priceRange があれば price_level は無視される
        sources: ["Google Places"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const priceLabel = screen.getByText("価格帯");
    const text = priceLabel.parentElement?.textContent ?? "";
    expect(text).toContain("1,500");
    expect(text).toContain("3,000");
    expect(text).toContain("〜");
  });

  it("price_range_jpy が start == end なら単一値「￥X,XXX」表示", () => {
    const item = makeItem({
      evidence: {
        price_range_jpy: { start: 2000, end: 2000 },
        sources: ["Google Places"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const priceLabel = screen.getByText("価格帯");
    const text = priceLabel.parentElement?.textContent ?? "";
    expect(text).toContain("2,000");
    expect(text).not.toContain("〜");
  });

  it("price_range_jpy 不在で price_level あれば ¥¥¥ 記号 fallback", () => {
    const item = makeItem({
      evidence: {
        price_level: 2,
        sources: ["Google Places"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    const priceLabel = screen.getByText("価格帯");
    const text = priceLabel.parentElement?.textContent ?? "";
    expect(text).toContain("¥¥");
    expect(text).not.toContain("〜");
  });

  it("複数 sources は ' / ' 区切りで連結", () => {
    const item = makeItem({
      evidence: {
        sources: ["Google Places", "楽天トラベル"],
      },
    });
    render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
    expect(screen.getByText("Google Places / 楽天トラベル")).toBeInTheDocument();
  });

  describe("Google Maps リンク", () => {
    it("place_id があれば Maps リンクが描画され、URL が公式 form", () => {
      render(
        <EvidenceModal item={makeItem()} open={true} onOpenChange={() => {}} />,
      );
      const link = screen.getByRole("link", { name: /Google Maps/ });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      const href = link.getAttribute("href");
      expect(href).toContain("https://www.google.com/maps/search/");
      expect(href).toContain("api=1");
      expect(href).toContain("query_place_id=ChIJxxx");
    });

    it("place_name を query に encode して載せる", () => {
      render(
        <EvidenceModal item={makeItem()} open={true} onOpenChange={() => {}} />,
      );
      const link = screen.getByRole("link", { name: /Google Maps/ });
      const href = link.getAttribute("href");
      expect(href).toContain(`query=${encodeURIComponent("大涌谷")}`);
    });

    it("place_name が null なら item.title を query に使う", () => {
      const item = makeItem({
        location: {
          place_id: "ChIJxxx",
          place_name: null,
          lat: null,
          lng: null,
          address: null,
        },
      });
      render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
      const link = screen.getByRole("link", { name: /Google Maps/ });
      const href = link.getAttribute("href");
      expect(href).toContain(`query=${encodeURIComponent("大涌谷")}`);
    });

    it("place_id が null ならリンクは描画されない", () => {
      const item = makeItem({
        location: {
          place_id: null,
          place_name: null,
          lat: null,
          lng: null,
          address: null,
        },
      });
      render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
      expect(screen.queryByRole("link", { name: /Google Maps/ })).toBeNull();
    });

    it("location 自体が undefined でも crash しない（transit item 等のセーフガード）", () => {
      // 本番 Run 11 で発覚: transit item や location 持たない item で
      // `item.location.place_id` が undefined access → React render error。
      // optional chaining で吸収、Maps リンクは描画されない（fallbackTitle のみ）。
      const item = makeItem();
      // @ts-expect-error - 意図的に location を undefined にして runtime safety を test
      delete item.location;
      expect(() =>
        render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />),
      ).not.toThrow();
      expect(screen.queryByRole("link", { name: /Google Maps/ })).toBeNull();
    });

    it("aria-label に「新しいタブ」表記を含む", () => {
      render(
        <EvidenceModal item={makeItem()} open={true} onOpenChange={() => {}} />,
      );
      const link = screen.getByRole("link", { name: /Google Maps/ });
      expect(link.getAttribute("aria-label")).toContain("新しいタブ");
    });
  });

  describe("lodging 表記の自然化 (Task B2)", () => {
    it("lodging item で opening_hours 不在のとき '終日' 表記を表示する", () => {
      const item = makeItem({
        item_type: "lodging",
        evidence: { sources: ["楽天トラベル"] },
      });
      render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
      const hoursLabel = screen.getByText("営業時間");
      const text = hoursLabel.parentElement?.textContent ?? "";
      // 「— 不明」ではなく「終日」を含む
      expect(text).not.toContain("— 不明");
      expect(text).toContain("終日");
    });

    it("lodging item で評価が不在のとき '評価情報なし' 表記を表示する", () => {
      const item = makeItem({
        item_type: "lodging",
        evidence: { sources: ["楽天トラベル"] },
      });
      render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
      const ratingLabel = screen.getByText("評価");
      const text = ratingLabel.parentElement?.textContent ?? "";
      expect(text).toContain("評価情報なし");
    });

    it("lodging 以外で opening_hours 不在は '— 不明' 維持", () => {
      const item = makeItem({
        item_type: "activity",
        evidence: { sources: ["Google Places"] },
      });
      render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
      const hoursLabel = screen.getByText("営業時間");
      const text = hoursLabel.parentElement?.textContent ?? "";
      expect(text).toContain("— 不明");
    });
  });

  describe("楽天トラベルリンク (external_url)", () => {
    it("evidence.external_url があるとき楽天トラベルリンクを表示する", () => {
      const item = makeItem({
        evidence: {
          sources: ["楽天トラベル"],
          external_url: "https://hb.afl.rakuten.co.jp/test",
        },
      });
      render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
      const link = screen.getByLabelText(/楽天トラベルで詳細を開く/);
      expect(link).toHaveAttribute("href", "https://hb.afl.rakuten.co.jp/test");
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    });

    it("evidence.external_url が無いとき楽天リンクは表示されない", () => {
      const item = makeItem({
        evidence: { sources: ["Google Places"] },
      });
      render(<EvidenceModal item={item} open={true} onOpenChange={() => {}} />);
      expect(screen.queryByLabelText(/楽天トラベルで詳細を開く/)).toBeNull();
    });
  });

  describe("a11y", () => {
    it("dialog 要素が title と aria-labelledby で関連付けされている", () => {
      render(
        <EvidenceModal item={makeItem()} open={true} onOpenChange={() => {}} />,
      );
      const dialog = screen.getByRole("dialog");
      const labelledBy = dialog.getAttribute("aria-labelledby");
      expect(labelledBy).toBeTruthy();
      const title = document.getElementById(labelledBy as string);
      expect(title?.textContent).toContain("大涌谷");
    });

    it("閉じるボタン (Phosphor X) のクリックで onOpenChange(false, ...) が呼ばれる", async () => {
      const user = userEvent.setup();
      const onOpenChange = vi.fn();
      render(
        <EvidenceModal
          item={makeItem()}
          open={true}
          onOpenChange={onOpenChange}
        />,
      );
      const closeBtn = screen.getByRole("button", { name: /閉じる/ });
      await user.click(closeBtn);
      // base-ui Dialog の onOpenChange は (open, details, eventDetails) で呼ばれる。
      // ここでは「最初の引数が false」だけ確認する。
      expect(onOpenChange).toHaveBeenCalled();
      expect(onOpenChange.mock.calls[0]?.[0]).toBe(false);
    });
  });
});
