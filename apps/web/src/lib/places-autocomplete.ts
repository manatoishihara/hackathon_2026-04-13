/**
 * Maps JavaScript API `Places` ライブラリのローダ（ブラウザ側、Phase 2.1 polish）。
 *
 * 役割:
 * - `AnchorPicker` 等の Place Autocomplete UI から呼び出される
 * - `@googlemaps/js-api-loader` v2 の `setOptions` + `importLibrary("places")` を
 *   singleton で保持し、複数コンポーネントが同時 mount しても 1 回しか SDK を
 *   ロードしない
 * - 失敗 promise は singleton から外して再試行可能に
 *
 * 前提:
 * - `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` が HTTP referrer 制限付きで発行されている
 *   （サーバキーとは別、apps/web/src/lib/transit.ts と同じキーを使用）
 * - **Google Cloud Project で「Places API (New)」が enabled** であること。
 *   Routeful の本番プロジェクトは New のみ enable し、legacy "Places API" は
 *   enable していない。`PlaceAutocompleteElement` は New のみで動作する公式 API
 *   （developers.google.com/maps/documentation/javascript/place-autocomplete-new）。
 *
 * `transit.ts` の routes ライブラリ singleton と並走する独立 singleton。
 * `setOptions({ key, v })` は Maps loader 内部で 1 回のみ効くため、両者で同じ key
 * を渡せば後勝ちで上書きされず安全。
 *
 * 履歴:
 * - 2026-04-25 初版: legacy `google.maps.places.Autocomplete` 用 loader として作成
 * - 2026-04-25 改訂: smoke test で「legacy Places API not enabled」が出たため、
 *   `PlaceAutocompleteElement` (new web component, Places API (New) のみで動作) に
 *   切替。loader の戻り値型 `google.maps.PlacesLibrary` は変更なし（同型に
 *   PlaceAutocompleteElement / Place / PlacePrediction が含まれる）。
 */

import { importLibrary, setOptions } from "@googlemaps/js-api-loader";

export class PlacesConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlacesConfigError";
  }
}

/**
 * `@types/google.maps` v3.64.0 の `PlacesLibrary` interface には
 * `PlaceAutocompleteElement` のキーが含まれていない（class 宣言は存在するが
 * library 戻り値型にだけ漏れている）。runtime では公式 docs パターン
 * `(await importLibrary("places")).PlaceAutocompleteElement` で取得可能なので、
 * ここで型を補完する。types 側に取り込まれたら削除する。
 */
export type PlacesLibraryWithAutocompleteElement = google.maps.PlacesLibrary & {
  PlaceAutocompleteElement: typeof google.maps.places.PlaceAutocompleteElement;
};

let placesLibraryPromise: Promise<PlacesLibraryWithAutocompleteElement> | null =
  null;

/**
 * Places ライブラリを取得する。複数回呼ばれても SDK ロードは 1 回のみ。
 *
 * 戻り値は `PlacesLibrary & { PlaceAutocompleteElement }`。
 *
 * @throws {PlacesConfigError} SSR 環境 / API キー未設定時
 */
export async function loadPlacesLibrary(): Promise<PlacesLibraryWithAutocompleteElement> {
  if (typeof window === "undefined") {
    throw new PlacesConfigError(
      "loadPlacesLibrary must run in the browser (typeof window === 'undefined')",
    );
  }
  if (placesLibraryPromise) return placesLibraryPromise;

  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
  if (!apiKey) {
    throw new PlacesConfigError(
      "NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY is not set. Configure it in .env.local and reload.",
    );
  }

  setOptions({ key: apiKey, v: "weekly" });
  const attempt = importLibrary(
    "places",
  ) as Promise<PlacesLibraryWithAutocompleteElement>;
  placesLibraryPromise = attempt;
  attempt.catch(() => {
    if (placesLibraryPromise === attempt) {
      placesLibraryPromise = null;
    }
  });
  return attempt;
}

/** テスト専用: singleton をリセットする。 */
export function _resetPlacesLoaderForTests(): void {
  placesLibraryPromise = null;
}
