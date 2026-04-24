import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceBadge } from "./EvidenceBadge";

describe("EvidenceBadge", () => {
  it("verified バッジは sources[0] をラベルにする", () => {
    render(<EvidenceBadge confidence="verified" sources={["Google Places"]} />);
    const badge = screen.getByText(/Google Places/);
    expect(badge).toHaveAttribute("data-variant", "verified");
  });

  it("estimated バッジは推定ラベルを出す", () => {
    render(<EvidenceBadge confidence="estimated" sources={["LLM"]} />);
    const badge = screen.getByText(/推定/);
    expect(badge).toHaveAttribute("data-variant", "estimated");
  });

  it("unknown バッジは不明ラベルを出す", () => {
    render(<EvidenceBadge confidence="unknown" sources={[]} />);
    const badge = screen.getByText(/不明/);
    expect(badge).toHaveAttribute("data-variant", "unknown");
  });

  it("verified で sources 空なら fallback ラベル（検証済み）になる", () => {
    render(<EvidenceBadge confidence="verified" sources={[]} />);
    expect(screen.getByText(/検証済み/)).toBeInTheDocument();
  });
});
