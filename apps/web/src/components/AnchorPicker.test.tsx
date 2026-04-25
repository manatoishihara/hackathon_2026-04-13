import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnchorPicker } from "./AnchorPicker";

describe("AnchorPicker", () => {
  it("shows empty state with input and add button", () => {
    render(<AnchorPicker value={[]} onChange={() => {}} />);
    expect(screen.getByLabelText("place_id")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "追加" })).toBeInTheDocument();
  });

  it("renders existing place_ids as chips", () => {
    render(
      <AnchorPicker
        value={["ChIJ_one", "ChIJ_two"]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("ChIJ_one")).toBeInTheDocument();
    expect(screen.getByText("ChIJ_two")).toBeInTheDocument();
  });

  it("calls onChange when adding a place_id via input + add button", () => {
    const onChange = vi.fn();
    render(<AnchorPicker value={["ChIJ_one"]} onChange={onChange} />);
    const input = screen.getByLabelText("place_id") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ChIJ_two" } });
    fireEvent.click(screen.getByRole("button", { name: "追加" }));
    expect(onChange).toHaveBeenCalledWith(["ChIJ_one", "ChIJ_two"]);
  });

  it("ignores empty / whitespace-only input", () => {
    const onChange = vi.fn();
    render(<AnchorPicker value={[]} onChange={onChange} />);
    const input = screen.getByLabelText("place_id") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "追加" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("ignores duplicate place_id", () => {
    const onChange = vi.fn();
    render(<AnchorPicker value={["ChIJ_one"]} onChange={onChange} />);
    const input = screen.getByLabelText("place_id") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ChIJ_one" } });
    fireEvent.click(screen.getByRole("button", { name: "追加" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes a chip when X button clicked", () => {
    const onChange = vi.fn();
    render(
      <AnchorPicker
        value={["ChIJ_one", "ChIJ_two"]}
        onChange={onChange}
      />,
    );
    const removeButtons = screen.getAllByRole("button", { name: /削除/ });
    fireEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenCalledWith(["ChIJ_two"]);
  });

  it("disables input + add button at max 3 anchors", () => {
    render(
      <AnchorPicker
        value={["a", "b", "c"]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByLabelText("place_id")).toBeDisabled();
    expect(screen.getByRole("button", { name: "追加" })).toBeDisabled();
  });
});
