import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThemePicker, THEME_OPTIONS } from "./ThemePicker";

describe("ThemePicker", () => {
  it("renders all 6 theme options with Japanese labels", () => {
    render(<ThemePicker value={null} onChange={() => {}} />);
    for (const { label } of THEME_OPTIONS) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("invokes onChange with theme key when clicking a chip", () => {
    const onChange = vi.fn();
    render(<ThemePicker value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "温泉" }));
    expect(onChange).toHaveBeenCalledWith("onsen");
  });

  it("highlights the currently selected theme via aria-pressed", () => {
    render(<ThemePicker value="art" onChange={() => {}} />);
    const artButton = screen.getByRole("button", { name: "アート" });
    expect(artButton).toHaveAttribute("aria-pressed", "true");
    const onsenButton = screen.getByRole("button", { name: "温泉" });
    expect(onsenButton).toHaveAttribute("aria-pressed", "false");
  });

  it("toggles off (onChange(null)) when clicking the currently-selected chip", () => {
    const onChange = vi.fn();
    render(<ThemePicker value="onsen" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "温泉" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
