# Future Extensions

現在のスコープには含めないが、データモデル・アーキテクチャはこれらの拡張を見越して設計されている。ハッカソンプレゼンで「今後の展望」として言及できる。

## 1. リモート同期対応（Phase 3 以降）

### 背景

現在は**対面で1端末を囲む**利用を想定している。将来的にはリモートで複数端末から同時編集したいニーズに応える。

### 実装方針

Supabase Realtime を導入するだけで大部分が動く。追加実装は以下：

```typescript
// apps/web/src/stores/planStore.ts に追記
const channel = supabase
  .channel(`plan:${planId}`)
  .on('postgres_changes',
    { event: '*', schema: 'public', table: 'plan_items', filter: `plan_id=eq.${planId}` },
    (payload) => {
      // ローカルステートを自動更新
      handleRemoteChange(payload);
    }
  )
  .subscribe();
```

### 追加で必要な設計

- **マルチカーソル表示**: 誰がどこを見ているかをリアルタイムに可視化
  - Supabase Presence 機能を使用
- **楽観的ロック**: 同じアイテムを2人が同時編集したときの競合解決
  - `updated_at` タイムスタンプで判定、後勝ちまたはユーザーに選ばせる
- **編集中ロック**: 誰かが編集中のアイテムには「編集中」インジケータを出す
- **プレゼンス**: 参加者のオンライン/オフライン状態

### 予想される課題

- Realtime の接続切断時の再同期ロジック
- オフライン時のローカル編集をオンライン復帰時にマージする設計
- モバイル端末のバッテリー消費（常時 WebSocket 接続）

## 2. 当日の旅のしおりビュー

### ユースケース

プラン確定後、旅行当日にスマホで見る画面。

- オフライン対応（Service Worker でキャッシュ）
- 次の予定までのカウントダウン
- 現在地から次のスポットへの簡易ルート表示
- チェックイン機能（「今ここにいる」を記録）

### 技術選定

- PWA として配信（Next.js の manifest + sw 対応）
- IndexedDB でプランデータをキャッシュ
- Background Sync API で軽微な同期

## 3. プランのバージョニング

### ユースケース

「前の案の方がよかった」に応えるための履歴機能。

- 生成されたプランを `plan_versions` テーブルに保存
- 編集・再生成のたびにスナップショットを取る
- 任意のバージョンに戻せる

### データモデル追加

```sql
CREATE TABLE plan_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  snapshot JSONB NOT NULL, -- plan + all items + participants の全体スナップショット
  created_at TIMESTAMPTZ DEFAULT NOW(),
  note TEXT
);

CREATE UNIQUE INDEX idx_plan_versions ON plan_versions(plan_id, version_number);
```

## 4. Evidence Pack の学習的改善

### ユースケース

ユーザーの行動ログから「好まれるスポット」「避けられるスポット」を学習し、次回の Evidence Pack 構築時にスコアリングに反映。

### 実装

- `plan_item_feedback` テーブルに「削除された」「代替案を選んだ」等のアクションを記録
- 夜間バッチで place_id ごとに集計
- Evidence Pack 構築時に集計スコアを relevance_tags に加味

これは PipSmith の「知識の三層（hypothesis → pattern → rule）」と同じ思想。

## 5. 複数言語対応

### 対応言語候補

- 英語（外国人観光客向け）
- 中国語簡体字・繁体字（訪日客の最大セグメント）
- 韓国語

### 実装方針

- i18n は next-intl
- LLM プロンプトは言語別に分岐
- Places API の `languageCode` パラメータで表示名を切替
- UI テキストは JSON 辞書（`apps/web/src/locales/`）

## 6. 予約連携

### ユースケース

生成されたプランのスポットや宿をそのまま予約できる。

- レストラン: OpenTable / 食べログ / ホットペッパー連携
- 宿: 楽天トラベル（すでに Phase 2 で連携）、じゃらん、Booking.com
- 交通: えきねっと、スマート EX、JR 各社

### 注意点

- 予約 API はパートナー契約が必要なものが多い
- アフィリエイト連携で収益化の道筋をつけつつ、UX を損なわないように設計

## 7. AI エージェント化

### ユースケース

「プラン完成後も AI が伴走する」旅のコンパニオン。

- 旅行当日: 遅延情報を取得し、自動でプラン再提案
- 旅行後: 写真・コメントから思い出アルバムを生成
- 次回のプラン: 過去の旅から好みを学習

### 実装方針

- Claude Agent SDK / OpenAI Assistants API の活用
- MCP でツール群を提供（乗換、地図、予約、SNS 投稿等）

## ハッカソン発表時の「今後の展望」構成例

```
現在: 対面での旅行計画体験を Evidence-based で実現

次の一手:
- リモート同期対応 → 遠距離の友人とも使える
- 当日のしおりビュー → 計画から実行までシームレス
- 学習的改善 → 使うほど精度が上がる
- 予約連携 → プラン → 予約 → 思い出まで一気通貫
```

これらは全て現在のアーキテクチャの自然な拡張であり、作り直し不要。この「拡張性のある設計」自体も技術的な評価ポイントになる。
