import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TransportModeSelector } from "./TransportModeSelector";

describe("TransportModeSelector", () => {
  it("renders both modes with Japanese labels", () => {
    render(<TransportModeSelector value="all_modes" onChange={() => {}} />);
    expect(screen.getByLabelText(/車も使う/)).toBeInTheDocument();
    expect(screen.getByLabelText(/公共交通機関のみ/)).toBeInTheDocument();
  });

  it("marks the current mode as checked", () => {
    render(<TransportModeSelector value="public_transit_only" onChange={() => {}} />);
    const publicRadio = screen.getByLabelText(/公共交通機関のみ/) as HTMLInputElement;
    expect(publicRadio.checked).toBe(true);
    const allRadio = screen.getByLabelText(/車も使う/) as HTMLInputElement;
    expect(allRadio.checked).toBe(false);
  });

  it("calls onChange when user selects a different mode", () => {
    const onChange = vi.fn();
    render(<TransportModeSelector value="all_modes" onChange={onChange} />);
    fireEvent.click(screen.getByLabelText(/公共交通機関のみ/));
    expect(onChange).toHaveBeenCalledWith("public_transit_only");
  });

  it("exposes role=radiogroup for SR a11y", () => {
    render(
      <TransportModeSelector value="all_modes" onChange={() => {}} ariaLabelledBy="hd" />,
    );
    const group = screen.getByRole("radiogroup");
    expect(group).toBeInTheDocument();
    expect(group.getAttribute("aria-labelledby")).toBe("hd");
  });
});
