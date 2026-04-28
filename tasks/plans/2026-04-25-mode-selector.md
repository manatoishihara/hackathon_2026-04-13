# Phase 2.1 出発モード切替（お任せ / アンカー / テーマ）

**ステータス**: 設計（2026-04-25 セッション、Manato 単独）
ブランチ: `feat/mode-selector`

## 背景と価値

Routeful は対面合意形成ツール。現状は `start_mode = 'auto'` ハードコードで「お任せ」生成のみ。
3 つのモードを切り替えられると **「対面でその場で議論軸を変えながら何回も生成」** ができ、
ハッカソン demo の中核体験になる。

| モード | UX | 内部処理 |
|---|---|---|
| お任せ (auto) | デフォルト、何も追加入力なし | 現状動作通り |
| アンカー (anchor) | 必ず含めたいスポットを 1〜3 件指定 | pack に anchor place を強制注入 + LLM に「必ず slot に割当てろ」指示 |
| テーマ (theme) | 温泉 / アート / グルメ等から 1 つ選択 | pack 構築時に検索 keyword を bias + LLM に slot 配分を bias |

## 既存資産

- `Plan.start_mode: 'auto' | 'anchor' | 'theme'` ✅ shared-types / Pydantic 既存
- `Plan.mode_payload: Record<string, unknown> | null` ✅ 同上
- `start_mode` / `mode_payload` は既に DB INSERT までフロー通ってる（フロントは `auto` 固定で送信）
- LCaMO 構造化 Assembly (Phase 1.3e) で hallucination 0% / success 100% を達成済 → 拡張する基盤として安定

## 設計方針

### A. 型を discriminated union で締める（3 点同期）

現状 `mode_payload: Record<string, unknown> | null` は緩すぎ。新規:

```typescript
// shared-types
export type AutoModePayload = null;
export type AnchorModePayload = { anchor_place_ids: string[] }; // 1〜3 件
export type ThemeModePayload = { theme: ThemeKey };
export type ThemeKey = 'onsen' | 'art' | 'gourmet' | 'nature' | 'history' | 'experience';

export type ModePayload = AutoModePayload | AnchorModePayload | ThemeModePayload;
```

`Plan.mode_payload` は `ModePayload` に narrow（既存 `Record<string, unknown> | null` 廃止）。
Pydantic 側も `Union[None, AnchorModePayload, ThemeModePayload]` で discriminated にする
（`start_mode` 値で判定）。

### B. フロント実装

#### B-1. UI 構造（`/plan/new` フォームに追加）

```
[基本情報]
[予算配分スライダー]
[参加者タブ]
─── 新規追加 ───
[モード選択]
  [ ] お任せ AI に全部おまかせ（現行と同じ）
  [ ] アンカー 必ず行きたい場所を決める → [Places Autocomplete + chip list]
  [ ] テーマ こだわりで絞り込み → [温泉/アート/グルメ/自然/歴史/体験]
─────────────
[プランを生成]
```

#### B-2. 新規コンポーネント

| ファイル | 責務 |
|---|---|
| `apps/web/src/components/ModeSelector.tsx` | 3 モード radio + 各モードの sub UI を切替表示 |
| `apps/web/src/components/AnchorPicker.tsx` | Places Autocomplete (Maps JS の Places ライブラリ) + 選択済 chips（×ボタンで削除）|
| `apps/web/src/components/ThemePicker.tsx` | 6 個の theme chip ボタン（toggle、1 つだけ選択）|

#### B-3. zod schema 拡張（`apps/web/src/lib/schemas/planForm.ts`）

```typescript
const modeSchema = z.discriminatedUnion('start_mode', [
  z.object({ start_mode: z.literal('auto'), mode_payload: z.null() }),
  z.object({
    start_mode: z.literal('anchor'),
    mode_payload: z.object({
      anchor_place_ids: z.array(z.string()).min(1).max(3),
    }),
  }),
  z.object({
    start_mode: z.literal('theme'),
    mode_payload: z.object({
      theme: z.enum(['onsen', 'art', 'gourmet', 'nature', 'history', 'experience']),
    }),
  }),
]);
```

zod の `discriminatedUnion` でフォーム単位の整合性を担保。

### C. バックエンド実装

#### C-1. `apps/api/src/evidence/builder.py`

`build_evidence_pack(query: QueryContext)` が `query.start_mode` / `query.mode_payload` を見て分岐:

- **auto**: 現状通り（変更なし）
- **anchor**:
  - mode_payload.anchor_place_ids を `places.fetch_place_details(place_id)` で取得
  - 取得した PlacePoint を pack.places の **先頭に追加**（重複は dedupe）
  - 既存の text search keyword と並列で実行
- **theme**:
  - theme → 検索 keyword 拡張（例: `onsen` → `["箱根 温泉", "箱根 露天風呂", "箱根 旅館"]`）
  - 既存の関数 `_keywords_for_query(query)` に theme 分岐を追加

#### C-2. `apps/api/src/llm/prompt.py` (v2.0.0)

`build_user_prompt` に `mode_context` セクション追加:

- **auto**: 何も追加しない
- **anchor**: `必須スポット: 以下の place_id を必ず slot に割当てよ: [pid1, pid2]`
- **theme**: `テーマ: <theme_label_jp>。slot 構成と place 選定をこのテーマに沿わせよ`

system.md の rule リストには追記しない（attention dilution 回避、Phase 1.3e で確認済）。
mode_context は user prompt の追加 section で済ませる。

#### C-3. `apps/api/src/llm/assembly.py`

anchor モードでは「LLM が anchor を slot に割当てなかった場合」の post-validation を追加:

- assembly 完了後、`anchor_place_ids` 全てが何らかの slot に含まれるか check
- 1 件でも欠けたら `AnchorMissingError` raise → generator が retry プロンプトに inject

## TDD ステップ

1. **型 3 点同期**（shared-types → Pydantic → test_schema_parity）
2. **zod schema** test 追加
3. **builder の anchor 分岐** test（mock Places fetch）
4. **builder の theme 分岐** test（keyword 拡張）
5. **prompt builder の mode_context 出力** test（v1/v2 両方）
6. **assembler の anchor 検証** test
7. **frontend ModeSelector** vitest + Testing Library
8. **frontend AnchorPicker / ThemePicker** vitest

## 完了条件

- [ ] `pytest -m "not integration"` 全 PASS（既存 283 + 新規 ~15 = ~298 件）
- [ ] `pnpm --filter web test` 全 PASS（既存 61 + 新規 ~10 = ~71 件）
- [ ] `pnpm --filter web exec tsc --noEmit` PASS
- [ ] ローカル `pnpm dev` で 3 モード触れて、各 mode で plan 生成が走る（実 OpenAI 呼び出し 1 回ずつ）
- [ ] anchor mode: 指定した place が plan に含まれる
- [ ] theme mode: pack の places が bias される（diagnose_pack.py 同等のスクリプトで確認可能）

## 非スコープ

- アンカー候補の autocomplete UI 詳細（最低限 Maps JS Places ライブラリで動けば OK、デザイン仕上げはメンバー C）
- テーマの細かいカスタマイズ（6 つ固定）
- mode 別の budget breakdown 既定値（Phase 2.2 で別途）

## 想定リスク

- **アンカー place の opening_hours が無い**: Places API Details 取得で `opening_hours` が null なケースがある。assembler の `eligible_for_slots` 計算が空になり、どの slot にも割当てられず `IneligiblePlaceForSlotError`。
  - 対処: anchor 時は eligibility を強制 OK にする（user の明示意思 > 営業時間の自動チェック）
- **アンカー数が増えると slot 不足**: 2 日プランで slot 10 個、anchor 5 個なら成立するが、anchor 8 個だと無理
  - 対処: フロント zod で max=3 に制限、UI でも「最大 3 つ」明示
- **テーマと参加者の希望が衝突**: 「テーマ=アート」だけど参加者全員が「温泉」希望、みたいな case
  - 対処: テーマは hint 扱い、参加者希望のほうを優先する旨を user prompt に明記

## 実装順（branch: feat/mode-selector）

1. **Step 1**: 型 3 点同期（shared-types / Pydantic / test_schema_parity）
2. **Step 2**: backend: builder anchor 分岐 + test
3. **Step 3**: backend: builder theme 分岐 + test
4. **Step 4**: backend: prompt builder mode_context + test
5. **Step 5**: backend: assembler anchor 検証 + test
6. **Step 6**: frontend: zod schema 拡張 + test
7. **Step 7**: frontend: ModeSelector + 3 sub component
8. **Step 8**: frontend: /plan/new に組み込み
9. **Step 9**: 結合: ローカル dev で 3 モード動作確認
10. **Step 10**: コミット提案 + lessons.md 反映
