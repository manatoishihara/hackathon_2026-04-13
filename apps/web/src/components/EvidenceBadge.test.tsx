import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

  describe("onClick prop", () => {
    it("onClick 未指定なら span でレンダされ、focusable でない", () => {
      render(<EvidenceBadge confidence="verified" sources={["Google Places"]} />);
      const badge = screen.getByText(/Google Places/);
      expect(badge.tagName).toBe("SPAN");
      // role="button" もない
      expect(screen.queryByRole("button")).toBeNull();
    });

    it("onClick 指定時は button でレンダされ、aria-label に title を含む", () => {
      const onClick = vi.fn();
      render(
        <EvidenceBadge
          confidence="verified"
          sources={["Google Places"]}
          onClick={onClick}
          ariaLabelTitle="箱根神社"
        />,
      );
      const button = screen.getByRole("button", { name: /箱根神社/ });
      expect(button.tagName).toBe("BUTTON");
      expect(button).toHaveAttribute("type", "button");
      expect(button).toHaveAttribute("data-variant", "verified");
      expect(button.getAttribute("aria-label")).toContain("箱根神社");
      expect(button.getAttribute("aria-label")).toContain("根拠");
    });

    it("onClick 指定時にクリックで callback が呼ばれる", async () => {
      const user = userEvent.setup();
      const onClick = vi.fn();
      render(
        <EvidenceBadge
          confidence="verified"
          sources={["Google Places"]}
          onClick={onClick}
          ariaLabelTitle="箱根神社"
        />,
      );
      await user.click(screen.getByRole("button"));
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("onClick 指定時に Enter キーで callback が呼ばれる（button 標準動作）", async () => {
      const user = userEvent.setup();
      const onClick = vi.fn();
      render(
        <EvidenceBadge
          confidence="verified"
          sources={["Google Places"]}
          onClick={onClick}
          ariaLabelTitle="箱根神社"
        />,
      );
      const button = screen.getByRole("button");
      button.focus();
      await user.keyboard("{Enter}");
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("onClick 指定時に Space キーで callback が呼ばれる（button 標準動作）", async () => {
      const user = userEvent.setup();
      const onClick = vi.fn();
      render(
        <EvidenceBadge
          confidence="verified"
          sources={["Google Places"]}
          onClick={onClick}
          ariaLabelTitle="箱根神社"
        />,
      );
      const button = screen.getByRole("button");
      button.focus();
      await user.keyboard(" ");
      expect(onClick).toHaveBeenCalledTimes(1);
    });
  });
});
