# Evidence Pack — LLM プロンプト設計の正典

このドキュメントは Routeful のコア技術の中心。**実装はこの仕様から外れてはならない**。

## 思想

LLM 単体で旅行プランを作らせると、以下のハルシネーションが頻繁に起きる：

- 存在しない店名・施設名を作り出す
- 実際の営業時間外の訪問を提案する
- 実在しない電車の便名・時刻を書く
- 移動時間を過小/過大に見積もる

**解決策**: LLM に「意味」だけ担当させ、「数値・固有名詞」は外部APIから構造化データとして注入する。これが Evidence Pack。

LCaMO 研究で得た知見「**LLM は意味空間を、数値空間は専用モジュールを**」の直接応用。

## データ構造

```typescript
type EvidencePack = {
  query_context: QueryContext;          // 何を求められているか
  places: PlacePoint[];                 // 使用可能なスポット候補（LLM はこの中からのみ選べる）
  transit_matrix: TransitEdge[];        // スポット間の経路情報（時刻・運賃つき）
  lodging_options?: LodgingOption[];    // 宿泊候補（Phase 2）
  budget_constraints: BudgetConstraints;// 予算配分の制約
  temporal_constraints: TemporalConstraints; // 日程の制約
};

type QueryContext = {
  region: string;
  start_date: string; // ISO
  end_date: string;
  departure_point: string;
  start_mode: 'auto' | 'anchor' | 'theme';
  mode_payload?: Record<string, unknown>;
  participants: {
    name: string;
    wishes: string;
    tags: string[];
  }[];
};

type PlacePoint = {
  place_id: string;              // Google Places ID（LLM はこのIDでのみ参照）
  name: string;
  category: string[];            // ["restaurant", "japanese"]
  lat: number;
  lng: number;
  address: string;
  opening_hours: string[];       // 曜日別の "09:00-18:00" 形式
  price_level: 1 | 2 | 3 | 4 | null;
  rating: number | null;
  user_ratings_total: number | null;
  relevance_tags: string[];      // 参加者希望とのマッチ度ラベル
};

type TransitEdge = {
  from_place_id: string;
  to_place_id: string;
  mode: 'train' | 'bus' | 'walk' | 'car';
  route_summary: string;         // "小田急線 特急はこね"
  duration_min: number;
  fare_jpy: number | null;
  candidate_departures: string[]; // 出発時刻の候補 ["09:15", "09:45", ...]
};

type BudgetConstraints = {
  total_jpy_per_person: number;
  breakdown_percent: {
    lodging: number;
    meal: number;
    activity: number;
    transit: number;
  };
  breakdown_jpy: {  // percent を金額に変換済み
    lodging: number;
    meal: number;
    activity: number;
    transit: number;
  };
};

type TemporalConstraints = {
  start_datetime: string;
  end_datetime: string;
  total_days: number;
  check_in_earliest: string; // "15:00"
  check_out_latest: string;  // "10:00"
};
```

## Pack 構築フロー

Evidence Pack は **サーバーとフロントの 2 段構築**になる。日本の transit 情報は
Google の Directions / Routes サーバー API から取れないため、ブラウザの Maps JS
SDK DirectionsService で取得して API に戻す（`tasks/lessons.md` 参照）。

```
[サーバー] POST /api/evidence/places
1. QueryContext から候補キーワードを生成（Phase 1.2 は決定論、Phase 1.3+ で LLM 化検討）
   例: "箱根 温泉" "箱根 和食" "箱根 観光"
2. 各キーワードで Places API text search（並列、各 top 10）
3. 重複を place_id で dedupe、上位 15 件に cap
4. （Phase 1.2 スキップ）各 place について Place Details を取得、参加者希望とのマッチを
   relevance_tags 付与 — Phase 1.3 で実装
5. 予算と時間の制約を展開
6. base_pack（transit_matrix は空）と evidence_pack_id（TTL 15 分程度）を返す

[フロント] ブラウザ上で Maps JS SDK DirectionsService
7. places のうち「直線距離 10km 以内」のペアで transit を取得
   - 最大ペア数: 20（places 15 件なら理論上 105 ペアだが、距離 10km フィルタで大幅削減）
   - 並列呼び出し: 最大 5（DirectionsService のクォータ破裂防止）
   - 各呼び出しタイムアウト: 2 秒（全体を 10 秒以内に収める）
   - 上記の具体数値は Phase 1.3 実装時に実測から調整する
   → TransitEdge[] を組み立てる
   → 各 TransitEdge は有向（A→B と B→A は別レコード）、from/to_place_id は places に含まれる ID

[サーバー] POST /api/plans/generate
8. evidence_pack_id + transit_matrix を受信
9. **Transit Validator**（Phase 1.3 で実装、現状は未実装）:
   - Pydantic Field 制約: 値域 / 文字長 / HH:mm / 件数上限（pack.py で既に防衛）
   - place_id が Evidence Pack.places に含まれること
   - 有向エッジの重複排除
10. サーバー短期キャッシュから取り出した Evidence Pack と validate 済み transit_matrix を
    マージして最終 Evidence Pack を再構成
    （クライアント送信データは validate 済み値のみを使う、生データは LLM に渡さない）
11. 宿泊候補がある場合、楽天トラベルAPIで検索（Phase 2）
12. 最終 Evidence Pack を LLM プロンプトに注入
```

**⚠️ Phase 1.2 の状態**: Transit Validator はまだ実装されておらず、`/api/evidence/places`
と `/api/plans/generate` のエンドポイント自体もまだ存在しない。`build_evidence_pack()` は
`transit_matrix=[]` を返すので、現時点では攻撃面は表に出ていない。Phase 1.3 でこれらを
同時に実装する。

## LLM プロンプト設計

### System Prompt

```text
あなたは旅行プランナーです。以下の制約の下で、JSON でプランを出力してください。

# 絶対ルール（違反は重大なバグ）
1. evidence_pack.places に含まれる place_id のみ使用せよ。架空のスポットを作るな
2. transit アイテムは evidence_pack.transit_matrix から選んだ経路のみ使用せよ
3. 時刻は必ず ISO 8601 形式、start_time < end_time を守れ
4. budget_constraints.breakdown_jpy を守れ（各カテゴリの合計がそれを超えない）
5. 全 activity / meal の start_time が opening_hours 内であること
6. 出力は以下の JSON Schema に厳密に従うこと

# JSON Schema
<ここにスキーマを展開>

# 参加者の希望の扱い
- 全員の希望を読み、妥協点を探れ。特定の 1 人の希望だけに偏らない
- wishes_text と tags の両方を参照
- 全員が「まあまあ満足」する配分を目指す（誰かが大満足で誰かが不満、は避ける）

# 出力品質
- description は 40〜80 文字。そこに行く理由が参加者に伝わる文章
- 時間の余裕を持たせる。移動 5 分ギリギリのような無理な配置は避ける
- 食事の時間は 60〜90 分、観光は 60〜180 分を目安に

出力以外の前置き・説明は不要。JSON のみを返せ。
```

### User Prompt Template

```text
# 旅行の基本情報
{query_context_json}

# 利用可能なスポット (Evidence Pack)
{evidence_pack_places_json}

# 経路情報（スポット間の移動）
{transit_matrix_json}

# 予算制約
{budget_constraints_json}

# 宿泊候補（指定がある場合）
{lodging_options_json}

上記情報のみを使ってプランを JSON で生成せよ。
```

## 出力 JSON Schema

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "order_index": { "type": "integer" },
          "item_type": { "type": "string", "enum": ["activity", "meal", "transit", "lodging"] },
          "title": { "type": "string" },
          "description": { "type": "string", "maxLength": 150 },
          "start_time": { "type": "string", "format": "date-time" },
          "end_time": { "type": "string", "format": "date-time" },
          "place_id": { "type": ["string", "null"] },
          "cost_jpy": { "type": ["integer", "null"] },
          "cost_confidence": { "type": "string", "enum": ["verified", "estimated", "unknown"] },
          "transit_ref": {
            "type": ["object", "null"],
            "description": "item_type=transit の場合、transit_matrix の from/to で該当 edge を参照",
            "properties": {
              "from_place_id": { "type": "string" },
              "to_place_id": { "type": "string" },
              "departure_time": { "type": "string" }
            }
          }
        },
        "required": ["order_index", "item_type", "title", "start_time", "end_time", "cost_confidence"]
      }
    }
  },
  "required": ["items"]
}
```

## 検証（validator.py）

LLM 出力を受け取ったら、以下を全て通すまで reject：

1. **Schema 検証**: `pydantic.ValidationError` を吐かない
2. **place_id 実在検証**: 全 `place_id` が `evidence_pack.places` に含まれる
3. **時刻検証**: `start_time < end_time`、かつ `opening_hours` 内
4. **transit 整合性**: `item_type=transit` の場合、`transit_matrix` に該当経路が存在
5. **予算超過検証**: カテゴリ別合計が `budget_constraints.breakdown_jpy` を超えない
6. **時系列検証**: 全アイテムを `start_time` で昇順にしたとき、重複・逆転がない

いずれか失敗したらリトライ（最大 2 回）。それでもダメなら `PlanGenerationError` を返し、フロントで「再生成」ボタンを出す。

## コスト・トークン管理

- Places を全フィールド渡すと 1 place あたり 500 token 超。必要フィールドだけ抽出
- transit_matrix は全ペアではなく近接ペアのみ（距離 10km 以内）
- Evidence Pack 全体で 10,000 token 以内を目安（超えたら上位スコアで絞る）

## バージョニング

プロンプトは `apps/api/src/llm/prompts/` に yaml で配置し、バージョン番号をつける。A/B テスト時は env var `PROMPT_VERSION` で切替可能に。
