# External API Rules

外部 API（Google Cloud / Maps Platform / OpenAI / Supabase / 楽天 / Mapbox 等）を新規導入・新規 SDK class を呼び出す前に必ず守ること。
2 回以上同種の失敗が発生した運用ルールが昇格して定着している。失敗の系譜は `tasks/lessons.md` を参照。

## Google Cloud SDK 4 階層 checklist

Maps Platform / Places / Routes / Directions / Cloud Storage / 等を含む、Google Cloud のあらゆる API を **JS SDK / Python SDK / 直 fetch 経由で呼ぶ前**に必ず以下 4 階層を全部 ✅ してから実装着手せよ。

### 1. SDK class の存在確認
- `google.maps.<X>`、`@google-cloud/<pkg>` 等で呼び出したい class / function が **`@types` / 公式 docs に現存している**か
- `deprecated` 警告だけ気にして実装し始めると、project 設定（階層 2）で詰む。「deprecated でも動く」は project の API enable 状況に依存
- **新 / 旧 API がある場合は「新を使う」を default**（Places API (New) / Routes API 等）

### 2. Cloud project で該当 API が **Enabled** か
- Cloud Console → APIs & Services → Library で対応 API が有効になっているか
- 例: `google.maps.DirectionsService` を呼ぶには **Directions API** か **Routes API** が enable 必須
- 例: `google.maps.places.PlaceAutocompleteElement` を呼ぶには **Places API (New)** が enable 必須
- legacy API を呼ぶ場合は **legacy API も enable** が必要（新 API enable だけでは legacy class は動かない）

### 3. API key の **API restrictions** に該当 API が allowlist されているか
- Cloud Console → Credentials → 該当 key →「キーの制限」「API の制限」
- **「Maps JavaScript API のみ」のような最小許可は危険**。後から `DirectionsService.Route` / `PlaceAutocompleteElement` 等を呼ぶ際に必ず追加忘れが起きる
- **新規 key を発行する時点で「将来呼ぶ可能性がある API」も含めて allowlist に入れる**（Routeful 構成では **Maps JavaScript API + Places API (New) + Directions API** が最低限）
- 制限変更の反映には 1〜5 分かかる場合がある

### 4. HTTP referrer / IP 制限に呼び出し元 origin が入っているか
- ブラウザキー: HTTP referrer 制限に **`https://<vercel-domain>/*`** + ローカル開発用 `http://localhost:3000/*` を両方追加
- サーバキー: IP 制限に **Render outbound IP**（無料 plan は固定 IP 不可なので IP 制限スキップ可）
- 反映には 1〜5 分

### 失敗パターンと探偵法

| 観測されるエラー | 原因の階層 | 確認方法 |
|---|---|---|
| `class is not a constructor` / `TypeError: ... is not a function` | 1 (SDK class) | docs で class 名を確認 |
| `This API project is not authorized to use this API` | 2 (Cloud project enable) | Library で API 名を検索 |
| `REQUEST_DENIED` / `Requests to this API ... are blocked` (status 403) | 3 (API key allowlist) | Credentials の key 設定 |
| `RefererNotAllowedMapError` / `IpAddressNotAllowed` | 4 (referrer/IP) | Credentials の key 制限 |

REQUEST_DENIED が複数 endpoint で連発 = **キーが API restrictions で絞られすぎている可能性が大**。endpoint 単独で reject されているか、key 全体で reject されているかを切り分ける。

### キー別 API 必要性早見表（Routeful 構成、ブラウザキー / サーバキーで別運用）

ブラウザキー（`NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY`、Vercel env）とサーバキー（`GOOGLE_MAPS_API_KEY`、Render env）は **別の API restrictions / Application restrictions が必要**。混同して片方に全部入れたり、片方を忘れると本番で REQUEST_DENIED / 403 が出続ける。

#### ブラウザキー
| API 名 | 用途 | コード参照 |
|---|---|---|
| Maps JavaScript API | base SDK ロード | `apps/web/src/lib/transit.ts` (loader), `apps/web/src/components/MapView.tsx` |
| Places API (New) | `PlaceAutocompleteElement`（AnchorPicker） | `apps/web/src/components/AnchorPicker.tsx`, `apps/web/src/lib/places-autocomplete.ts` |
| **Directions API (legacy)** | `new google.maps.DirectionsService()` で transit_matrix 取得 | `apps/web/src/lib/transit.ts:394` |

**注意**: フロントは `importLibrary("routes")` で routes library を import するが、実際に呼ぶのは **legacy `DirectionsService`**。なので enable / allowlist が必要なのは **「Routes API」(new) ではなく「Directions API」(legacy)**。命名で迷ったら `apps/web/src/lib/transit.ts` の class 名を確認せよ。

Application restrictions: **HTTP referrers**（`https://<vercel-domain>/*` + `http://localhost:3000/*`）。

#### サーバキー
| API 名 | 用途 | コード参照 | 必要度 |
|---|---|---|---|
| Places API (New) | text search + Place Details | `apps/api/src/evidence/places.py:17,18` | **必須**（MVP 動作） |
| Routes API | DRIVE estimate | `apps/api/src/evidence/routes.py:30` | Phase 2 のみ |
| Geocoding API | `/healthz` 疎通確認 / 地域推定 | `apps/api/src/external/health.py:139` | あれば良い |

Application restrictions: **None**（Render Free は固定 IP 不可、IP 制限不可）。

新規 API を呼ぶコードを追加する時は、**まずどちら側のキーで叩くかを明示**してから、対応するキーの API restrictions を更新する。

### 同種失敗の系譜（**2 回目で本ルール昇格**、2026-04-26）

1. **2026-04-26 (1 回目)**: `PlaceAutocompleteElement` 統合後、smoke test で `places.googleapis.com` が 403 (`Requests to this API ... AutocompletePlaces are blocked`)。原因: Phase 1.10 で発行したブラウザキーの API restrictions が「Maps JavaScript API のみ」で **Places API (New) を含んでいなかった**
2. **2026-04-26 (2 回目)**: 本番 E2E verify (`/plan/new` auto モード)、migration 05 適用後の Run 2 で `MapsRequestError: DIRECTIONS_ROUTE: REQUEST_DENIED` が連発、`transit_matrix: []` で `/api/plans/generate → 500`。原因: 同じブラウザキーが **Directions API を含んでいなかった**

両ケースとも **同じ階層 #3** の見落とし、別 API での再発。今後は SDK class を導入する設計時点で 4 階層を埋めるのを強制する。

## OpenAI API

詳細は `.claude/rules/llm-rules.md` を参照。本ファイルは外部 API 共通の運用面のみ。

- API key は **rotate 可能な前提で、code に直接埋めず env 経由**（`OPENAI_API_KEY`）
- prompt を変える時は `PROMPT_VERSION` env で切り替え可能に（rollback 容易、cost 比較容易）

## Supabase

詳細は `.claude/rules/data-model-sync.md` を参照。本ファイルは外部 API としての注意点のみ。

- **anon サインインは `auth.users` にしか行を作らない**。custom テーブルとの FK で繋ぐ場合、必ず mirror トリガを `supabase/migrations/` に migration として配置（lessons.md「RLS 42501 真因は FK 違反」参照）
- service_role key は **サーバ側でのみ使用**、フロントには絶対に配信しない（env も `NEXT_PUBLIC_` prefix 禁止）
- RLS policy は **migration ファイルが正典**、本番 drift を防ぐため Production Branch から SQL Editor で再適用する運用を維持

## 共通の運用原則

### API key rotation
- API key を rotate する際は、Cloud Console / Vercel env / Render env の **3 箇所セット**で更新
- rotate 直後の reflection ラグ（1〜5 分）を考慮して、smoke test を本番でやり直す

### 4 階層 checklist の暗記
新規 SDK class を導入する全ての PR で、コミット前に下記を impl 者が言語化できるか確認:
- 階層 1: 呼ぶ class の名前と公式 docs URL
- 階層 2: project で enable される API 名
- 階層 3: API key の API restrictions に追加すべき名前
- 階層 4: referrer / IP 制限に追加すべき origin / IP

これを 30 秒で答えられない場合は、4 階層のうちどこかが脆弱。impl を始める前に検証 checklist を tasks/plans/ に書き起こすこと。
