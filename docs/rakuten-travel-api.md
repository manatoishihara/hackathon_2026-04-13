# 楽天トラベル API 利用ガイド

本プロジェクトで実際に動作確認した内容をまとめた参照ドキュメント。

---

## API の種類と使い分け

| API | エンドポイント名 | 用途 |
|---|---|---|
| **施設検索** | SimpleHotelSearch | ホテル名・位置情報・最安値目安を取得（日付・空室関係なし） |
| **空室検索** | VacantHotelSearch | 指定日・人数で空室あるホテルと実際の料金を取得 |

**ルール**: ホテル名と座標だけ欲しいなら SimpleHotelSearch、実際の宿泊料金・空室状況が必要なら VacantHotelSearch を使う。

---

## 認証情報（必須）

2026年2月9日の新 API 移行以降、以下の2つが必須。

| 環境変数 | パラメータ名 | 形式 | 説明 |
|---|---|---|---|
| `RAKUTEN_APPLICATION_ID` | `applicationId` | UUID形式（例: `bf17fc69-...`） | アプリID |
| `RAKUTEN_ACCESS_KEY` | `accessKey` | `pk_` で始まる文字列 | アクセスキー |
| `RAKUTEN_AFFILIATE_ID` | `affiliateId` | `xxxxxxxx.xxxxxxxx....` | アフィリエイトID（任意） |

取得場所: https://webservice.rakuten.co.jp/app/list

---

## 1. 施設検索 API（SimpleHotelSearch）

### 取得できる情報

- ホテル名（`hotelName`）
- 位置情報（`latitude` / `longitude`）
- 最安値目安（`hotelMinCharge`）※実際の空室料金ではない
- 施設URL（`hotelInformationUrl`）
- 評価（`reviewAverage`）

### 重要: `datumType=1` が必須

省略すると緯度経度が**日本測地系・秒単位**で解釈され、全く別の場所を検索してしまう。
`datumType=1` を付けることで WGS84 度単位（Google Maps と同じ系）になる。

### リクエスト URL

```
https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20170426
  ?applicationId={APPLICATION_ID}
  &accessKey={ACCESS_KEY}
  &format=json
  &latitude={緯度}        # WGS84 度単位（例: 35.2327）
  &longitude={経度}       # WGS84 度単位（例: 139.1069）
  &searchRadius=3         # 半径 km（0.1〜3.0）
  &datumType=1            # ← 必須！これがないと別の場所を検索する
  &hits=5                 # 取得件数（最大30）
  &sort=standard          # 近い順
  &responseType=middle
```

### 動作確認済みリンク（箱根）

```
https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20170426?applicationId=bf17fc69-ec1b-45c9-914e-0885d491a2c7&accessKey=pk_egccPTCYNEBYbQAQPKjhzy9qzp4VYlHO03c0kz6o8g9&affiliateId=53374f89.9deecdc4.53374f8a.b14caea3&format=json&latitude=35.2327&longitude=139.1069&searchRadius=3&datumType=1&hits=5&sort=standard&responseType=middle
```

### レスポンス構造（formatVersion=1 デフォルト）

```json
{
  "hotels": [
    {
      "hotel": [
        {
          "hotelBasicInfo": {
            "hotelNo": 12345,
            "hotelName": "箱根温泉旅館 〇〇",
            "latitude": 35.23,
            "longitude": 139.10,
            "hotelMinCharge": 15000,
            "hotelInformationUrl": "https://travel.rakuten.co.jp/hotel/12345/"
          }
        },
        {
          "hotelRatingInfo": {
            "reviewAverage": 4.5
          }
        }
      ]
    }
  ]
}
```

---

## 2. 空室検索 API（VacantHotelSearch）

### 取得できる情報

SimpleHotelSearch の情報に加えて:

- **実際の宿泊料金**（人数・日程指定後の確定価格）
- **空室状況**（その日程で予約可能かどうか）
- **1泊・複数泊ごとの料金**（checkoutDate で宿泊数を指定）

### リクエスト URL

```
https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426
  ?applicationId={APPLICATION_ID}
  &accessKey={ACCESS_KEY}
  &format=json
  &latitude={緯度}
  &longitude={経度}
  &searchRadius=3
  &datumType=1
  &checkinDate={YYYY-MM-DD}   # チェックイン日
  &checkoutDate={YYYY-MM-DD}  # チェックアウト日（1泊: checkin+1日、2泊: checkin+2日）
  &adultNum={人数}             # 大人の人数（例: 2）
  &maxCharge={上限金額}        # 1室1泊あたりの上限（円）
  &hits=5
  &sort=standard
```

### 宿泊日数の指定方法

| 宿泊数 | checkinDate | checkoutDate |
|---|---|---|
| 1泊 | 2026-06-01 | 2026-06-02 |
| 2泊 | 2026-06-01 | 2026-06-03 |
| 3泊 | 2026-06-01 | 2026-06-04 |

### 動作確認済みリンク（箱根・2名・1泊・3万円以下）

```
https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426?applicationId=bf17fc69-ec1b-45c9-914e-0885d491a2c7&accessKey=pk_egccPTCYNEBYbQAQPKjhzy9qzp4VYlHO03c0kz6o8g9&affiliateId=53374f89.9deecdc4.53374f8a.b14caea3&format=json&latitude=35.2327&longitude=139.1069&searchRadius=3&datumType=1&checkinDate=2026-06-01&checkoutDate=2026-06-02&adultNum=2&maxCharge=30000&hits=5&sort=standard
```

---

## 3. エラー対応表

| エラー | 意味 | 対処 |
|---|---|---|
| `wrong_parameter: specify valid applicationId` | applicationId が空 or 無効 | 環境変数 `RAKUTEN_APPLICATION_ID` を確認 |
| `wrong_parameter: specify valid anyone set of parameters` | 座標・区分コード・hotelNo のいずれも未指定 | `latitude` + `longitude` + `datumType=1` を追加 |
| `wrong_parameter: keyword parameter is not valid` | keyword パラメータは新 API で非対応 | keyword を削除し座標検索に変更 |
| `REQUEST_CONTEXT_BODY_HTTP_REFERRER_MISSING` | Referer ヘッダーが登録 URL と不一致 | developer console のアプリ URL を `SITE_BASE_URL` に設定 |
| `too_many_requests` | リクエスト過多 | 時間を空けて再試行 |

---

## 4. Routeful での実装方針

- **SimpleHotelSearch を使用**（施設情報 + 最安値目安で LLM プロンプトに渡すには十分）
- 価格上限フィルタは API 側で指定不可のため、Python 側で `hotelMinCharge <= max_charge` でフィルタ
- 座標は Google Places で取得した places の重心座標を使用（builder.py で計算）
- 実装: `apps/api/src/evidence/lodging.py`

### 失敗した旧実装との差分

| 項目 | 旧（動かなかった） | 新（動作確認済み） |
|---|---|---|
| エンドポイント | `app.rakuten.co.jp/services/...` | `openapi.rakuten.co.jp/engine/...` |
| `accessKey` | なし | 必須 |
| 座標系 | `datumType` 未指定（秒単位として解釈） | `datumType=1`（WGS84 度単位） |
| 検索方式 | `keyword=箱根`（新 API 非対応） | `latitude` + `longitude` + `searchRadius` |
| レスポンスパース | 旧 API 構造（`hotel_entry[0]["hotelBasicInfo"]`） | 新 API 構造（`hotel_entry["hotel"][0]["hotelBasicInfo"]`） |
