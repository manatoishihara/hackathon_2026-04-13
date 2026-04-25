/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-this-alias -- Maps JS Places (New) の partial mock で any キャスト + activeElement = this のグローバル参照が必要 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// `@googlemaps/js-api-loader` を MockPlaceAutocompleteElement / MockPlacePrediction /
// MockPlace で置き換える。AnchorPicker 内部からは `loadPlacesLibrary` 経由で利用される。
vi.mock("@googlemaps/js-api-loader", () => ({
  setOptions: vi.fn(),
  importLibrary: vi.fn(async () => ({
    PlaceAutocompleteElement: MockPlaceAutocompleteElement,
  })),
}));

import { AnchorPicker } from "./AnchorPicker";
import { _resetPlacesLoaderForTests } from "@/lib/places-autocomplete";

// ==============================
// Mock 構造（PlaceAutocompleteElement / PlacePrediction / Place）
//
// 公式 docs パターン:
//   const place = event.placePrediction.toPlace();
//   await place.fetchFields({ fields: ["displayName"] });
//   const id = place.id;
//   const name = place.displayName;
// ==============================

type MockPlaceData = { id: string; displayName: string };

class MockPlace {
  public readonly id: string;
  public displayName: string | null = null;
  private readonly resolved: MockPlaceData;
  constructor(data: MockPlaceData) {
    this.id = data.id;
    this.resolved = data;
  }
  async fetchFields(opts: { fields: string[] }): Promise<void> {
    if (opts.fields.includes("displayName")) {
      this.displayName = this.resolved.displayName;
    }
  }
}

class MockPlacePrediction {
  constructor(private readonly data: MockPlaceData) {}
  toPlace(): MockPlace {
    return new MockPlace(this.data);
  }
}

let activeElement: MockPlaceAutocompleteElement | null = null;

class MockPlaceAutocompleteElement extends HTMLElement {
  public readonly opts: any;
  public value = "";
  private listeners = new Map<string, Set<EventListener>>();

  constructor(opts: any) {
    super();
    this.opts = opts;
    activeElement = this;
  }

  addEventListener(type: string, listener: EventListener): void {
    let set = this.listeners.get(type);
    if (!set) {
      set = new Set();
      this.listeners.set(type, set);
    }
    set.add(listener);
  }

  removeEventListener(type: string, listener: EventListener): void {
    this.listeners.get(type)?.delete(listener);
  }

  /** テストヘルパ: `gmp-select` event を発火 */
  _firePlaceSelect(data: MockPlaceData) {
    const set = this.listeners.get("gmp-select");
    if (!set) return;
    const ev = new Event("gmp-select") as any;
    ev.placePrediction = new MockPlacePrediction(data);
    for (const l of set) (l as EventListener)(ev);
  }

  _activeListenerCount(type: string) {
    return this.listeners.get(type)?.size ?? 0;
  }
}

// happy-dom は customElements.define を提供する。重複登録を許さないので一度だけ登録。
if (!customElements.get("mock-gmp-place-autocomplete")) {
  customElements.define(
    "mock-gmp-place-autocomplete",
    MockPlaceAutocompleteElement,
  );
}

async function selectPlace(data: MockPlaceData) {
  // useEffect の async loader 完走を待つ（micro-task 数回）
  await waitFor(() => {
    if (!activeElement) throw new Error("element not yet created");
  });
  activeElement!._firePlaceSelect(data);
  // gmp-select handler 内 `await place.fetchFields(...)` の完了を待つ
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
}

async function waitForElementMounted() {
  await waitFor(() => {
    if (!activeElement) throw new Error("element not yet created");
  });
}

// ==============================
// Tests
// ==============================

describe("AnchorPicker (Phase 2.1 polish: PlaceAutocompleteElement 統合)", () => {
  beforeEach(() => {
    _resetPlacesLoaderForTests();
    process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY = "pk-fake";
    activeElement = null;
  });

  afterEach(() => {
    delete process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
  });

  it("renders empty state with search combobox label", async () => {
    render(<AnchorPicker value={[]} onChange={() => {}} />);
    expect(screen.getByLabelText(/スポット検索/)).toBeInTheDocument();
    expect(screen.getByTestId("anchor-empty-state")).toBeInTheDocument();
  });

  it("constructs PlaceAutocompleteElement with includedRegionCodes=['jp']", async () => {
    render(<AnchorPicker value={[]} onChange={() => {}} />);
    await waitForElementMounted();
    expect(activeElement).not.toBeNull();
    expect(activeElement!.opts.includedRegionCodes).toEqual(["jp"]);
  });

  it("appends the autocomplete element into the host container", async () => {
    render(<AnchorPicker value={[]} onChange={() => {}} />);
    await waitForElementMounted();
    const host = screen.getByTestId("anchor-autocomplete-host");
    expect(host.contains(activeElement!)).toBe(true);
  });

  it("adds place_id to onChange and shows Japanese name in chip when user selects from autocomplete", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<AnchorPicker value={[]} onChange={onChange} />);
    await selectPlace({ id: "ChIJ_hakone_jinja", displayName: "箱根神社" });
    expect(onChange).toHaveBeenCalledWith(["ChIJ_hakone_jinja"]);

    // 親コンポーネントが新 value を渡す → chip が日本語名で描画される
    rerender(<AnchorPicker value={["ChIJ_hakone_jinja"]} onChange={onChange} />);
    expect(screen.getByText("箱根神社")).toBeInTheDocument();
  });

  it("falls back to place_id display when name is unknown (e.g., external value with no prior selection)", async () => {
    render(<AnchorPicker value={["ChIJ_unknown"]} onChange={() => {}} />);
    expect(screen.getByText("ChIJ_unknown")).toBeInTheDocument();
  });

  it("ignores duplicate place_id from autocomplete", async () => {
    const onChange = vi.fn();
    render(<AnchorPicker value={["ChIJ_existing"]} onChange={onChange} />);
    await selectPlace({ id: "ChIJ_existing", displayName: "既存" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("ignores selection when prediction has no id", async () => {
    const onChange = vi.fn();
    render(<AnchorPicker value={[]} onChange={onChange} />);
    // id を空にしたデータ → fetchFields 完了後も id が空 → 早期 return
    await selectPlace({ id: "", displayName: "noid" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes a chip when × button clicked", async () => {
    const onChange = vi.fn();
    render(
      <AnchorPicker value={["ChIJ_one", "ChIJ_two"]} onChange={onChange} />,
    );
    const removeButtons = screen.getAllByRole("button", { name: /削除/ });
    fireEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenCalledWith(["ChIJ_two"]);
  });

  it("hides combobox interaction at max 3 anchors (aria-hidden)", () => {
    render(<AnchorPicker value={["a", "b", "c"]} onChange={() => {}} />);
    const host = screen.getByTestId("anchor-autocomplete-host");
    expect(host.getAttribute("aria-hidden")).toBe("true");
  });

  it("does not add when 3-anchor limit reached even via autocomplete", async () => {
    const onChange = vi.fn();
    render(<AnchorPicker value={["a", "b", "c"]} onChange={onChange} />);
    await selectPlace({ id: "ChIJ_fourth", displayName: "4th" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes listener and detaches element on unmount", async () => {
    const { unmount } = render(<AnchorPicker value={[]} onChange={() => {}} />);
    await waitForElementMounted();
    expect(activeElement!._activeListenerCount("gmp-select")).toBe(1);
    const elementRef = activeElement!;
    unmount();
    expect(elementRef._activeListenerCount("gmp-select")).toBe(0);
    // detached: parentNode is null
    expect(elementRef.parentNode).toBeNull();
  });

  it("displays inline error when API key is missing", async () => {
    delete process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
    render(<AnchorPicker value={[]} onChange={() => {}} />);
    expect(
      await screen.findByText(/NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY/i),
    ).toBeInTheDocument();
  });
});
