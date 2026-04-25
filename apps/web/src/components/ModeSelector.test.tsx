import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ModeSelector } from "./ModeSelector";

describe("ModeSelector", () => {
  it("renders all 3 modes with Japanese labels", () => {
    render(<ModeSelector value="auto" onChange={() => {}} />);
    expect(screen.getByLabelText(/お任せ/)).toBeInTheDocument();
    expect(screen.getByLabelText(/アンカー/)).toBeInTheDocument();
    expect(screen.getByLabelText(/テーマ/)).toBeInTheDocument();
  });

  it("marks the current mode as checked", () => {
    render(<ModeSelector value="anchor" onChange={() => {}} />);
    const anchorRadio = screen.getByLabelText(/アンカー/) as HTMLInputElement;
    expect(anchorRadio.checked).toBe(true);
    const autoRadio = screen.getByLabelText(/お任せ/) as HTMLInputElement;
    expect(autoRadio.checked).toBe(false);
  });

  it("calls onChange when user selects a different mode", () => {
    const onChange = vi.fn();
    render(<ModeSelector value="auto" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/テーマ/));
    expect(onChange).toHaveBeenCalledWith("theme");
  });
});
