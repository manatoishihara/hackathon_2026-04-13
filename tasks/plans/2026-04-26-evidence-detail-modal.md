# Phase 2.5: Evidence 詳細モーダル

**ステータス**: codex review 1 回目 完了 → Blocker 2 / Major 4 / Minor 1 を反映済み（実装着手準備完了）
**ブランチ**: `feat/evidence-detail-modal`（develop から生やす）
**スコープ**: B（5 フィールド表示 + Google Maps 外部リンク）
**想定 LOC**: ~180（test 含めて ~250）
**想定時間**: 2〜3 時間
**OpenAI コスト**: 0（フロント完結、既存 Evidence 型のフィールドを表示するだけ）

## 1. 目的（demo インパクト）

Routeful の USP は「**ハルシネーション 0% / Evidence-based**」（Phase 1.3e で 50+ サンプル累計 hallucination 0% 達成済）。この USP を demo で**体感的に伝えるコンポーネント**が現在欠けている。

PlanItem の `EvidenceBadge` は色 + アイコン + ラベル 1 行のみで、「verified である根拠」が見えない。
バッジクリック → モーダルで根拠を展開できるようにすることで:
- 演者: 「ここにきっちり Evidence が紐づいてます」と 1 タップで demo 可能
- 聴衆: 「営業時間も評価も Google Places の実データ」と即座に検証可能
- 「Google Maps で開く」リンクで実在性を体感的に証明

## 2. UX 設計

### トリガー

`EvidenceBadge` は **`onClick` prop の有無で要素を出し分ける**:
- `onClick` 指定あり: `<button type="button">` でレンダ、`aria-label={`${title} の根拠の詳細を見る`}` を渡す
- `onClick` 指定なし: 従来通り `<span>` を維持（既存呼び出しが壊れない、focusable にならない）
- カーソル `pointer` + hover で軽いリング表示（button 時のみ）
- キーボード操作: Tab フォーカス、Enter/Space で開く（button 標準動作）
- Codex Major 2 反映: `aria-label` は `item.title` を含めることで複数 PlanItem 並列時に文脈を保つ

### モーダル内容（B スコープ）

```
┌─────────────────────────────────┐
│ 大涌谷 の根拠           [×]     │  ← DialogTitle、明朝、PlanItem.title を表示
├─────────────────────────────────┤
│ 営業時間   09:00–17:00          │
│ 評価        ★ 4.5 / 5.0         │
│ 価格帯      ¥¥                  │
│ 出典        Google Places       │
│ 検証日時    2026-04-26 10:32    │
├─────────────────────────────────┤
│ [ Google Maps で開く ]          │  ← place_id があるときだけ表示、外部新規タブ
└─────────────────────────────────┘
```

- 各行: 左側ラベル（小、`text-secondary`）/ 右側値（明朝、`text-primary`）
- 価格帯（price_level 1〜4）: `¥` の枚数で表示、なし時「— 不明」
- 評価（rating + user_ratings_total）: `★ 4.5 / 5.0` または「— 不明」（user_ratings_total はスコープ外、簡素化）
- 検証日時: **`YYYY-MM-DD HH:mm` 固定 / `Asia/Tokyo` timeZone 固定**（Codex Blocker 2 反映、`Intl.DateTimeFormat` の `dateStyle/timeStyle` だと local 環境依存になるため `formatToParts` で組み立てる）
- 不在フィールド: 値部分を `— 不明` （`text-tertiary`、grayed）に
- 出典: `sources: string[]` を ` / ` 区切りで連結（空配列なら `— 不明`、`sources` だけ将来的に「— 取得元なし」に分離検討、Codex Minor）

### Google Maps リンク

- 表示条件: `item.location.place_id` が non-null
- URL: **`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(place_name ?? title)}&query_place_id=${encodeURIComponent(place_id)}`**（Codex Blocker 1 反映、Google 公式 Maps URLs の現行推奨 form。`api=1` 必須、`query` も必須、`query_place_id` で精度向上）
- `target="_blank"` + `rel="noopener noreferrer"`
- `aria-label="Google Mapsで開く（新しいタブ）"`（Codex Major 2 反映、新規タブ告知）
- フッター部に primary tone の outline button、Phosphor `ArrowSquareOut` icon
- place_id が無い場合（transit 等）はボタン自体を非表示

### スタイル

- shadcn/ui の `Dialog`（`@base-ui/react/dialog`）を流用、現状の Design Tokens に合わせる
- `DialogTitle` に明朝（既存 `font-heading text-base font-medium`）
- 行レイアウト: `grid grid-cols-[100px_1fr] gap-y-2`
- blue hour 配色: 値の見出しを Deep Navy、不在を `text-tertiary`、外部リンクボタンは `--color-primary` outline
- **Close button は Phosphor `X` を使う**（Codex Major 4 反映、shadcn Dialog の default は Lucide `XIcon`、Routeful 規約は Phosphor 優先）
  - 実装: `<DialogContent showCloseButton={false}>` + `EvidenceModal.tsx` 内で `<DialogClose>` をカスタム配置（Phosphor `X` icon + `aria-label="閉じる"`）

## 3. 変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `apps/web/src/components/EvidenceBadge.tsx` | `onClick` prop 追加（optional）、ありなら `<button type="button">` でレンダ + `aria-label`、無しなら `<span>` 維持。`data-variant` は両方に残す |
| `apps/web/src/components/EvidenceModal.tsx` | **新規**。`Dialog` を controlled で wrap、`item` から 5 フィールドを描画、Maps リンク条件付き表示、`<DialogContent showCloseButton={false}>` + Phosphor X close ボタンをカスタム配置 |
| `apps/web/src/components/PlanItem.tsx` | `useState(open)` 追加、`EvidenceBadge` に `onClick={() => setOpen(true)}` を渡し、`<EvidenceModal item={item} open={open} onOpenChange={setOpen} />` を末尾に配置 |
| `apps/web/src/components/EvidenceModal.test.tsx` | **新規**。badge click → open / fields 表示 / 不在フィールドの「— 不明」表示 / Maps リンクの条件付き表示 / 外部 URL 形式（`api=1` / `query` / encode 済 / `rel` / `target`） / `role="dialog"` と title の関連付け（aria-labelledby） |
| `apps/web/src/components/EvidenceBadge.test.tsx` | クリック挙動とキーボード操作（Enter/Space）テスト、`onClick` 未指定時に `span` のままで focusable でないことを追加 |
| `apps/web/src/lib/format.ts` | `formatVerifiedAt(iso?: string \| null): string` を追加。仕様: `iso` が string なら `YYYY-MM-DD HH:mm`（`Asia/Tokyo` 固定、`Intl.DateTimeFormat.formatToParts` で組み立て）、無効値 / null / undefined なら `"— 不明"` を返す |
| `apps/web/src/lib/format.test.ts` | `formatVerifiedAt` の単体テスト（valid ISO / null / undefined / 無効値 / DST timezone でも JST 固定で出ること） |

**型変更なし**。`Evidence` / `PlanItem` 型は既に必要なフィールドを持っている（`packages/shared-types/src/index.ts:104-110`）。
**API 変更なし**。サーバが返す `evidence` JSONB をそのまま使う。
**3 点同期不要**。

## 4. TDD 手順

### Step 1: `formatVerifiedAt` の単体テスト（先）→ 実装
- 入力: ISO 8601 文字列 (`"2026-04-26T01:32:00Z"`) / null / undefined / 無効値 (`"not-iso"`)
- 期待出力: `"2026-04-26 10:32"`（JST、UTC+9） / `"— 不明"` / `"— 不明"` / `"— 不明"`
- **DST / 環境タイムゾーン非依存テスト**: `process.env.TZ` を `"America/Los_Angeles"` に切り替えても同じ JST 結果を返すこと（`vi.stubEnv` または beforeAll で `process.env.TZ` を切替、formatToParts で実装）

### Step 2: `EvidenceBadge` の clickable 化（先 test）→ 実装
- `onClick` 指定時: `<button type="button">` でレンダされ、click で callback が呼ばれること
- Enter/Space キーで `onClick` が呼ばれること（button 標準動作）
- `aria-label` に `item.title` が含まれること
- `onClick` 未指定時: `<span>` のままで、`tabindex` が無く focusable でないこと（既存 PlanTimeline test の regression を防ぐ）

### Step 3: `EvidenceModal` 単体テスト（先）→ 実装
- `open=true` で 5 フィールドが描画される
- `opening_hours = undefined` / `rating = undefined` / `price_level = undefined` / `verified_at = undefined` / `sources = []` なら全行に「— 不明」表示（5 件分の独立 test）
- `place_id = null` なら Maps リンク非表示
- `place_id = "ChIJxxx"` & `place_name = "大涌谷"` なら:
  - `<a href="https://www.google.com/maps/search/?api=1&query=%E5%A4%A7%E6%B6%8C%E8%B0%B7&query_place_id=ChIJxxx">` が描画
  - `target="_blank"` + `rel="noopener noreferrer"` が付く
  - `aria-label="Google Mapsで開く（新しいタブ）"` が付く
- `place_name = null` の fallback として `item.title` が `query` に encode されること
- `onOpenChange(false)` で閉じる経路（DialogClose）
- **a11y**: `role="dialog"` 要素が `aria-labelledby` で DialogTitle と関連付けられていること（base-ui Dialog の default 動作確認）

### Step 4: `PlanItem` の統合（先 test）→ 実装
- バッジ click でモーダルが開くこと
- モーダル内に `item.title` が表示されること
- 複数 PlanItem 並列時に各 modal が独立して開閉する（参加者 5 人 / 観光地 4 件のシナリオで 1 件ずつ開閉確認）

### Step 5: 検証
- `pnpm --filter web test` 全件 PASS（既存 96 件 + 追加 ~10 件）
- `pnpm --filter web build` PASS（Next.js の ESLint 警告で fail しないこと）
- `pnpm --filter web exec tsc --noEmit` PASS

## 5. UI 耐久性チェック（frontend-design.md 必須）

- 長文 PlanItem.title（30 文字以上）でモーダルが崩れない
- 全フィールド null で「— 不明」5 行 + Maps リンク無し でも画面が成立
- 参加者 2〜5 人で各 PlanItem 別々のモーダルが正常に開閉
- mobile（375px）でモーダルが画面に収まる（max-w-[calc(100%-2rem)] が機能）
- ESC キーで閉じる（base-ui Dialog 標準）

## 6. リスク・考慮事項

### Risk: モバイル UX
- shadcn の Dialog は modal 形式。モバイルだと bottom sheet の方がベターだが、今回は Dialog 統一（Drawer 導入は scope 外）
- `max-w-sm` で smartphone でも収まる設計

### Risk: place_id の有効性
- LLM 生成の `place_id` は Phase 1.3e validator で `pack.places` に含まれる ID のみ許可済（hallucination 0%）
- Google Maps URL でその ID が解決できない場合は Maps 側で「場所が見つかりません」が表示される（fallback は不要、demo 失敗してもそれ自体が「Evidence の欠陥」を示す情報になるので隠さない）

### YAGNI で削ったもの
- Evidence 編集（読み取りのみ）
- Place の写真表示（Place Details 取得追加で API コスト発生、Phase 3 scope）
- 取得元の URL クリック透過（出典名表示のみ）
- ユーザレビュー数（user_ratings_total）→ rating だけで demo 訴求は十分

### Codex review 1 回目の反映状況
- ✅ Blocker 1: Maps URL を `?api=1&query=...&query_place_id=...` form に変更
- ✅ Blocker 2: `formatVerifiedAt` の signature を `(iso?: string | null): string`、出力 `YYYY-MM-DD HH:mm` を `Asia/Tokyo` 固定で `formatToParts` 組み立てに
- ✅ Major 1: EvidenceBadge を「`onClick` あり = button、無し = span」の条件分岐に
- ✅ Major 2: a11y `aria-label` に `item.title` 含める、Maps リンクは「新しいタブ」明示
- ✅ Major 3: TDD step に test 追加（`sources=[]` / `verified_at` 欠損 / URL encode / `rel` / `api=1` / `role="dialog"` 関連付け / DST 環境非依存 / 複数 PlanItem 独立開閉）
- ✅ Major 4: Dialog の close button を Phosphor X に置き換え（`showCloseButton={false}` + 自前配置）
- ✅ Minor 1: `sources` 表記、今は `— 不明` 統一、将来「— 取得元なし」検討メモ残す
- ✅ OK 1, 2: PlanItem 内 state 管理 + B スコープ、判断維持

### Codex review 2 回目（実装後）に確認してほしいポイント
1. 上記 Blocker / Major の反映が漏れなく実装されているか
2. `formatVerifiedAt` の `formatToParts` 実装が DST と環境 TZ 切替テストで本当に固定値を返すか
3. Phosphor close button の配置が base-ui Dialog の `<DialogClose>` でちゃんと閉じるか（render prop 経由が正しい）
4. EvidenceBadge の `<span>` / `<button>` 条件分岐が既存 EvidenceBadge.test.tsx を壊していないか

## 7. 完了基準

- [ ] 全テスト PASS（既存 + 新規）
- [ ] `pnpm --filter web build` PASS
- [ ] tsc clean
- [ ] PlanItem の EvidenceBadge を click で modal が開閉できる（手動確認、`NEXT_PUBLIC_USE_MOCKS=1 pnpm --filter web dev`）
- [ ] Codex 実装後 review で blocker 指摘無し
- [ ] commit 提案（user 手動 commit）

## 8. 参考

- 既存 EvidenceBadge: `apps/web/src/components/EvidenceBadge.tsx`
- shadcn Dialog: `apps/web/src/components/ui/dialog.tsx`（base-ui ベース）
- Evidence 型: `packages/shared-types/src/index.ts:104-110`
- frontend-design.md: blue hour 和モダン、明朝見出し、Phosphor アイコン、`Intl.NumberFormat('ja-JP')`
- Phase 2.5 の元タスク記述: `tasks/todo.md` の「2.5 Evidence 詳細モーダル」節
