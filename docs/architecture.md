# Architecture

## 全体構成

```
┌──────────────────────────────────────────────────────────────┐
│  Next.js on Vercel (apps/web)                                │
│  - Server Components + Client Components                     │
│  - Mapbox GL JS で地図描画                                    │
│  - Supabase client で DB 直接読み取り（RLS で保護）           │
└──────────┬───────────────────────────────────────────────────┘
           │ HTTPS (JSON)
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Flask on Render (apps/api)                                  │
│  - Evidence Pack Builder                                     │
│  - LLM Plan Generator                                        │
│  - Partial Regeneration                                      │
└─────┬────────────────┬──────────────────┬────────────────────┘
      │                │                  │
      ▼                ▼                  ▼
┌─────────┐   ┌─────────────────┐   ┌───────────────────┐
│ OpenAI  │   │ Google Maps     │   │ 楽天トラベル       │
│ GPT-4o  │   │ Platform        │   │ API (Phase 2)     │
│         │   │ - Places        │   │                   │
│         │   │ - Routes        │   │                   │
│         │   │ - Geocoding     │   │                   │
└─────────┘   └─────────────────┘   └───────────────────┘

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
2. [Web → API] POST /api/plans/generate に希望データを送信
   ↓
3. [API] Evidence Pack Builder:
   ├─ Places API で候補スポット検索（並列）
   ├─ Geocoding で座標確定
   └─ Routes API で候補経路の時刻・運賃を取得（並列）
   ↓
4. [API] LLM Plan Generator:
   ├─ Evidence Pack + 希望 + 予算配分 を prompt に注入
   ├─ OpenAI GPT-4o を JSON Schema 指定で呼び出し
   └─ 出力を validator で検証（ハルシネーション検出）
   ↓
5. [API → DB] 結果を Supabase plan_items テーブルに保存
   ↓
6. [API → Web] plan_id を返す
   ↓
7. [Web] /plan/[id] に遷移、Supabase から plan_items を直接読み取り描画
```

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
