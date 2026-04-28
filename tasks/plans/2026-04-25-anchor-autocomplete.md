# Phase 2.1 polish: AnchorPicker に Maps JS Places Autocomplete 統合

**ステータス**: ✅ 実装完了（2026-04-25 夕方、`PlaceAutocompleteElement` 版で着地）
ブランチ: `feat/anchor-autocomplete`

## 2026-04-25 補足: legacy `Autocomplete` → `PlaceAutocompleteElement` migrate

本設計書は当初 deprecated `google.maps.places.Autocomplete` を使う前提で書かれた
（章末「非スコープ」に「PlaceAutocompleteElement への移行はハッカソン範囲外」と記載）。
しかし実装後の smoke test で **「legacy Places API not enabled」** エラーが出た。

### 原因

Routeful の Google Cloud project は **「Places API (New)」だけ enable** していて、
legacy "Places API" は enable していなかった。`Autocomplete` (legacy class) は
legacy "Places API" が enable されていないと runtime で動かない（deprecated 警告とは別の話）。

公式 docs によると:
- `Autocomplete` (legacy) は **legacy "Places API"** を require
- `PlaceAutocompleteElement` (web component) は **"Places API (New)"** のみで動作
- Routeful のプロジェクト構成は (New) のみ enable → 後者で実装が正解

### Migration 結果

| 項目 | 旧（legacy `Autocomplete`） | 新（`PlaceAutocompleteElement`） |
|---|---|---|
| Class | `google.maps.places.Autocomplete` | `google.maps.places.PlaceAutocompleteElement` (HTMLElement subclass) |
| Required Cloud API | legacy "Places API" | "Places API (New)" |
| 国限定 | `componentRestrictions: { country: "jp" }` | `includedRegionCodes: ["jp"]` |
| 既存 `<input>` への attach | `new Autocomplete(input, opts)` | `new PlaceAutocompleteElement(opts); container.appendChild(element)` |
| 選択 event | `place_changed` listener | `gmp-select` event listener (PlacePredictionSelectEvent) |
| place_id 取得 | `ac.getPlace().place_id` | `event.placePrediction.toPlace()` then `place.id` |
| name 取得 | `getPlace().name`（即時取得、`fields: ["name"]` 要） | `await place.fetchFields({ fields: ["displayName"] })` |
| Shadow DOM | なし | あり（外側ラッパで装飾） |

### 公式 docs パターン採用

```typescript
const places = await loadPlacesLibrary();
const element = new places.PlaceAutocompleteElement({ includedRegionCodes: ["jp"] });
element.addEventListener("gmp-select", async (ev: Event) => {
  const selectEv = ev as google.maps.places.PlacePredictionSelectEvent;
  const place = selectEv.placePrediction.toPlace();
  await place.fetchFields({ fields: ["displayName"] });
  const id = place.id;
  const name = place.displayName ?? id;
  // form 更新...
});
container.appendChild(element);
```

### TS 型補完

`@types/google.maps` v3.64.0 の `PlacesLibrary` interface には
`PlaceAutocompleteElement` キーが**載っていない**（class 宣言は存在するが
library 戻り値型から漏れている）。`places-autocomplete.ts` で
`PlacesLibraryWithAutocompleteElement = PlacesLibrary & { PlaceAutocompleteElement: ... }`
を export してこれを補完。types 側に取り込まれたら削除。

### テスト戦略の変更

happy-dom で `HTMLElement` を継承した Mock を `new` するには `customElements.define()`
での登録が必要。`MockPlaceAutocompleteElement` を `mock-gmp-place-autocomplete` として
register する pattern。`gmp-select` event は `new Event("gmp-select")` の payload に
`placePrediction = new MockPlacePrediction(data)` を attach する。
`MockPlace.fetchFields` は `displayName` を resolved value から埋める。

### 検証結果

- [x] `pnpm --filter web test`: 13 ファイル / 96 件 PASS
- [x] `pnpm --filter web exec tsc --noEmit`: clean
- [x] `pnpm --filter web build`: 成功（次は localhost で smoke test）
- [ ] ローカル `pnpm dev` で `/plan/new` を開き、anchor mode で「箱根神社」と打って
      ドロップダウンから選択 → chip 表示確認（user 側で確認）

### 教訓

`tasks/lessons.md` 2026-04-25 エントリ「Cloud project の enable API と SDK class が
一致しているか実装前に検証する」に記録した。Google Maps Platform 系 SDK を選ぶ前に
「(a) その class が require する Cloud API、(b) 本プロジェクトで enable されている
API」を両方確認するワークフローに切替。

---

## （以下は当初の設計、legacy `Autocomplete` 前提で書かれた内容を残す）



## 背景

Phase 2.1 backend + frontend 配線は完了。AnchorPicker は MVP として「手動 place_id
貼付け」方式で commit 済。これを **Google Maps Places Autocomplete** で置き換え、
ユーザが「箱根神社」と打つ → 候補ドロップダウン → 選択 → chip に「箱根神社」と
日本語名で表示、内部的に place_id を保持する UX に格上げする。

ハッカソン demo で「対面で 2〜5 人が画面囲んで作る」コンセプトの体験価値を上げる。

## 既存資産

- `apps/web/src/lib/transit.ts` で `@googlemaps/js-api-loader` v2 (`setOptions` +
  `importLibrary("routes")`) を使う pattern が確立。これを `importLibrary("places")`
  で踏襲できる
- `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` は HTTP referrer 制限済、Places API も
  Maps JavaScript API key の制限内で利用可
- AnchorPicker の form 接続契約は `value: string[]`（place_id 配列）のまま維持
  （schema 変更なし）

## 設計方針

### A. ローダー集約 — `apps/web/src/lib/google-places.ts` 新規

`transit.ts` の `setOptions` + `importLibrary("places")` パターンを抽出した薄い helper:

```typescript
import { importLibrary, setOptions } from "@googlemaps/js-api-loader";

let _loaded = false;
let _loadPromise: Promise<google.maps.PlacesLibrary> | null = null;

export async function loadPlacesLibrary(): Promise<google.maps.PlacesLibrary> {
  if (_loadPromise) return _loadPromise;
  _loadPromise = (async () => {
    if (!_loaded) {
      const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
      if (!apiKey) throw new Error("NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY is not set");
      setOptions({ key: apiKey, v: "weekly", language: "ja", region: "JP" });
      _loaded = true;
    }
    return (await importLibrary("places")) as google.maps.PlacesLibrary;
  })();
  return _loadPromise;
}

export function resetPlacesLibrary(): void {
  // テスト用 reset。`_loaded`/`_loadPromise` を初期化
}
```

### B. AnchorPicker.tsx 改修

**Props は変更なし**（`value: string[]` / `onChange: (next: string[]) => void`）。
内部で**名前 lookup** を `useState<Map<string, string>>` で保持。

```typescript
const [names, setNames] = useState<Map<string, string>>(new Map());
const inputRef = useRef<HTMLInputElement>(null);
const acRef = useRef<google.maps.places.Autocomplete | null>(null);

useEffect(() => {
  let mounted = true;
  let listener: google.maps.MapsEventListener | null = null;
  (async () => {
    try {
      const lib = await loadPlacesLibrary();
      if (!mounted || !inputRef.current) return;
      const ac = new lib.Autocomplete(inputRef.current, {
        fields: ["place_id", "name"],
        componentRestrictions: { country: "jp" },
      });
      acRef.current = ac;
      listener = ac.addListener("place_changed", () => {
        const place = ac.getPlace();
        if (!place.place_id || !place.name) return;
        // 重複・上限チェックは外側関数で
        addAnchor(place.place_id, place.name);
      });
    } catch (err) {
      console.warn("AnchorPicker: places library load failed", err);
    }
  })();
  return () => {
    mounted = false;
    if (listener) listener.remove();
    acRef.current = null;
  };
}, []);
```

### C. Chip 表示

place_id をキーに `names.get(id) ?? id` で表示。**name 不明時は place_id にフォールバック**
（form の初期値が外部から来た場合、page.tsx の reset 時など）。

### D. Closure 罠の対処

useEffect の依存配列を空 `[]` にすると、effect 内の `addAnchor` が初期 `value` で
captureされてしまう。対策として **`valueRef` で最新値を ref 経由参照** するパターン:

```typescript
const valueRef = useRef(value);
useEffect(() => { valueRef.current = value; }, [value]);

const addAnchor = (placeId: string, name: string) => {
  const current = valueRef.current;
  if (current.includes(placeId)) return;
  if (current.length >= MAX_ANCHORS) return;
  setNames((m) => new Map(m).set(placeId, name));
  onChange([...current, placeId]);
};
```

## ファイル変更

| 新規 / 変更 | パス | 内容 |
|---|---|---|
| 新規 | `apps/web/src/lib/google-places.ts` | Loader helper（singleton + reset for tests） |
| 変更 | `apps/web/src/components/AnchorPicker.tsx` | Autocomplete attach + name lookup + ref パターン |
| 変更 | `apps/web/src/components/AnchorPicker.test.tsx` | `@googlemaps/js-api-loader` mock + Autocomplete simulator |

## テスト戦略

### vitest mock パターン（transit.test.ts 参照）

```typescript
vi.mock("@googlemaps/js-api-loader", () => ({
  setOptions: vi.fn(),
  importLibrary: vi.fn(async () => ({
    Autocomplete: MockAutocomplete,
  })),
}));

class MockAutocomplete {
  private listener: (() => void) | null = null;
  private nextPlace: { place_id?: string; name?: string } = {};

  constructor(public input: HTMLInputElement, public opts: unknown) {}
  addListener(_event: string, cb: () => void) {
    this.listener = cb;
    return { remove: () => { this.listener = null; } };
  }
  setNextPlace(place: { place_id: string; name: string }) {
    this.nextPlace = place;
  }
  triggerSelection() { this.listener?.(); }
  getPlace() { return this.nextPlace; }
}
```

### テストケース

1. 既存テスト（`value`/`onChange`/最大 3/重複拒否）はそのまま
2. **新規**: Autocomplete 経由で place 選択 → onChange が place_id 配列で呼ばれる
3. **新規**: 同じ user 操作で chip に「日本語名」が表示される（fallback 不要なケース）
4. **新規**: 外部から `value=["ChIJ..."]` を渡された case → name 不明なので chip は place_id 表示（fallback）
5. **新規**: 上限 3 件に達したら Autocomplete からの追加も拒否

## 完了条件

- [ ] `pnpm --filter web test` 全 PASS（既存 91 + 新規 ~5）
- [ ] `pnpm --filter web exec tsc --noEmit` clean
- [ ] `pnpm --filter web build` 成功
- [ ] ローカル `pnpm dev` で `/plan/new` を開き、anchor mode で「箱根神社」と打って
      ドロップダウンから選択 → chip 表示確認
- [ ] todo.md / lessons.md に反映、commit 提案

## 非スコープ

- 新しい `PlaceAutocompleteElement`（web component）への移行 → deprecated `Autocomplete`
  でハッカソン期間は OK
- 候補のスタイリング（Google デフォルトを使う）→ メンバー C のデザイン仕上げ範囲
- `componentRestrictions` を国別から地域別に切替（pack の region と連動）→ Phase 2.5 検討

## 想定リスク

1. **Google の Autocomplete UI が blue hour テーマと馴染まない**
   - ドロップダウンは Google 提供で外見をいじりにくい
   - 緩和: ハッカソン demo で「Google の力借りてるんですよ」と説明、Google らしさ自体が信頼感
2. **HTTP referrer 制限で本番 Vercel から弾かれる可能性**
   - ブラウザキーに `https://hackathon-2026-04-13.vercel.app/*` 追加済（Phase 1.10 で対応）
   - localhost:3000/* も追加済
3. **`place.name` が undefined のケース**
   - `getPlace()` 直後に `place.place_id && place.name` で両方確認、片方欠ければ早期 return
4. **同 place_id を複数回選択した時の重複**
   - addAnchor で `current.includes(placeId)` check 既に対処
5. **vitest 環境（happy-dom）で `google` global が undefined**
   - `vi.mock` で `@googlemaps/js-api-loader` を完全に上書きするので `google` global を
     直接参照しない設計が必要

## 実装順

1. **Step 1**: research subagent で Maps JS Places Autocomplete API 現状確認 +
   vitest mock pattern 確認
2. **Step 2**: `lib/google-places.ts` 新規（既存 transit.ts pattern 踏襲）
3. **Step 3**: AnchorPicker.tsx 改修（ref pattern + Autocomplete attach）
4. **Step 4**: AnchorPicker.test.tsx mock 書き換え（既存 test も維持）
5. **Step 5**: フル test + tsc + build
6. **Step 6**: ローカル smoke test（pnpm dev で実 SDK 動作確認）
7. **Step 7**: todo.md / lessons.md 反映、commit 提案
