# Architecture

## 全体構成

```
┌──────────────────────────────────────────────────────────────┐
│  Next.js on Vercel (apps/web)                                │
│  - Server Components + Client Components                     │
│  - Mapbox GL JS で地図描画                                    │
│  - Maps JS SDK DirectionsService で日本 transit 取得          │
│  - Supabase client で DB 直接読み取り（RLS で保護）           │
└──────────┬───────────────────────────────────────────────────┘
           │ HTTPS (JSON)
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Flask on Render (apps/api)                                  │
│  - Evidence Pack Builder (places のみ)                       │
│  - Transit Validator (フロントが送る transit_matrix を検証)   │
│  - LLM Plan Generator                                        │
│  - Partial Regeneration                                      │
└─────┬────────────────┬──────────────────┬────────────────────┘
      │                │                  │
      ▼                ▼                  ▼
┌─────────┐   ┌─────────────────┐   ┌───────────────────┐
│ OpenAI  │   │ Google Maps     │   │ 楽天トラベル       │
│ GPT-4o  │   │ Platform        │   │ API (Phase 2)     │
│         │   │ - Places        │   │                   │
│         │   │ - Routes (DRIVE)│   │                   │
│         │   │ - Geocoding     │   │                   │
└─────────┘   └─────────────────┘   └───────────────────┘

※ Google Maps Platform の Directions / Routes サーバー API は日本国内の
  transit データを返さない（tasks/lessons.md 参照）。JP 向け transit は
  ブラウザの Maps JS SDK DirectionsService 経由で取得する。

┌──────────────────────────────────────────────────────────────┐
│  Supabase                                                    │
│  - PostgreSQL (sessions, plans, plan_items, participants)    │
│  - 匿名認証（セッション ID で識別）                            │
│  - Row Level Security で他セッションへのアクセスを遮断        │
└──────────────────────────────────────────────────────────────┘
```

## データフロー（プラン生成）

```
1. [Web] ユーザーが希望入力を完了し「プランを生成」ボタンを押す
   ↓
2. [Web → API] POST /api/evidence/places
   ├─ 希望データ / 予算 / 日程 / 参加者を送信
   ├─ API が Places API で候補スポット検索（並列、dedupe）
   ├─ 予算・時間制約を展開
   ├─ Evidence Pack 本体（places + 予算 + 時間制約、transit_matrix は空）を
   │   サーバー短期キャッシュに格納
   └─ Web にはフロントが transit 取得に使う最小サブセットのみ返す:
       { evidence_pack_id, places: [{ place_id, name, lat, lng }] }
   ↓
3. [Web] Maps JS SDK DirectionsService:
   ├─ 距離 10km 以内のスポットペアに絞って transit 取得（最大 20 ペア、並列 5、
   │   各 2 秒タイムアウト — 具体上限は Phase 1.3 実装時に確定）
   └─ TransitEdge 配列を組み立てる（有向、A→B と B→A は別レコード）
   ↓
4. [Web → API] POST /api/plans/generate
   ├─ evidence_pack_id + transit_matrix を送信
   ├─ API が short-lived cache から Evidence Pack を取り出す
   ├─ Transit Validator で厳密検証:
   │   - Pydantic Field 制約（値域 / 文字長 / HH:mm、pack.py）
   │   - place_id が Evidence Pack.places に含まれること（Phase 1.3）
   │   - 件数上限 / 重複排除（Phase 1.3）
   └─ LLM にはサーバー再構成済み Evidence Pack のみ渡す
   ↓
5. [API] LLM Plan Generator:
   ├─ Evidence Pack + 希望 + 予算配分 を prompt に注入
   ├─ OpenAI GPT-4o を JSON Schema 指定で呼び出し
   └─ 出力を validator で検証（ハルシネーション検出）
   ↓
6. [API → DB] 結果を Supabase plan_items テーブルに保存
   ↓
7. [API → Web] plan_id を返す
   ↓
8. [Web] /plan/[id] に遷移、Supabase から plan_items を直接読み取り描画
```

※ base_pack のキャッシュには Supabase の一時テーブル（`evidence_pack_sessions`、
  TTL で自動掃除）を使う。単一インスタンスならメモリでもよいが Render の
  再起動で消えるのでサーバー間で共有できるストアの方が安定する。

## データフロー（部分再生成、Phase 2）

```
1. [Web] 特定の PlanItem に対して「代替案」ボタンを押す
   ↓
2. [Web → API] POST /api/plans/:id/items/:item_id/regenerate
   ├─ 前後のアイテム情報
   └─ 追加制約（「もっと静か」等、任意）
   ↓
3. [API] 周辺スポットの Evidence Pack を再構築（絞り込み）
   ↓
4. [API] LLM に「前後をこれで固定、この枠だけ代替案を出せ」と指示
   ↓
5. [API] 新アイテムを validate し、start_time / end_time を Routes API で再計算
   ↓
6. [API → DB] 該当アイテムのみ UPDATE（他アイテムは変更しない）
   ↓
7. [Web] 差分のみ再描画
```

## データフロー（手動編集）

```
1. [Web] PlanItem を削除 or 並び替え
   ↓
2. [Web → API] PATCH /api/plans/:id/items?reorder=[...]
   ↓
3. [API] 影響する区間のみ Routes API で再計算（並列）
   ↓
4. [API → DB] 影響する PlanItem の start_time / end_time / transit_to_next を UPDATE
   ↓
5. [Web] DB から読み直し描画
```

## 認証と権限

- **Supabase 匿名認証**: セッション作成時に JWT を発行、localStorage に保存
- **Row Level Security (RLS)**: `plans.owner_session_id = auth.uid()` で自身のプランのみ読み書き可能
- **共有 URL**: `share_token` カラムを使って、トークン付き URL では RLS をバイパスして読み取り可能にする（編集不可）

## スケーリング想定

ハッカソン用途では不要だが、運用開始時に検討すべき項目：

- Redis キャッシュ（Places API 結果、人気スポットは再検索を避ける）
- CDN（静的アセット、Mapbox タイルはもともと CDN 経由）
- LLM 呼び出しのコスト管理（1 セッション 3 回まで等のレート制限）

## 拡張方針（リモート同期対応、Phase 3 以降）

`docs/future-extensions.md` 参照。データモデル設計は最初からリモート同期を見越しており、Supabase Realtime の導入で WebSocket 経由の行変更ブロードキャストを追加するのみで対応可能。
