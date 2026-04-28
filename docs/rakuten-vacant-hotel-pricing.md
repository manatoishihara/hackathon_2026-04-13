# 楽天トラベル VacantHotelSearch — 1人あたりの1泊料金取得ガイド

VacantHotelSearch API で「指定した日程・人数で空室がある宿の実際の料金」を取得し、
1人あたりの1泊料金を正しく計算する手順をまとめる。

---

## 1. APIリクエスト

### エンドポイント

```
https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426
```

### 必須パラメータ

| パラメータ | 説明 | 例 |
|---|---|---|
| `applicationId` | アプリID（UUID形式） | `bf17fc69-...` |
| `accessKey` | アクセスキー（`pk_` で始まる） | `pk_egcc...` |
| `format` | レスポンス形式 | `json` |
| `latitude` | 緯度（WGS84 度単位） | `35.2327` |
| `longitude` | 経度（WGS84 度単位） | `139.1069` |
| `datumType` | **必須**。`1` = WGS84度単位。省略すると日本測地系秒単位として解釈され全く別の場所を検索する | `1` |
| `checkinDate` | チェックイン日（YYYYMMDD） | `20260601` |
| `checkoutDate` | チェックアウト日（YYYYMMDD） | `20260602` |
| `adultNum` | 大人の人数 | `2` |

### 任意パラメータ

| パラメータ | 説明 | 例 |
|---|---|---|
| `maxCharge` | 1泊の上限料金（円）| `30000` |
| `searchRadius` | 検索半径（km、最大3.0） | `3` |
| `hits` | 取得件数（最大30） | `5` |
| `sort` | 並び順（`standard` = 近い順） | `standard` |
| `affiliateId` | アフィリエイトID（任意） | `53374f89...` |

### 動作確認済みリンク（箱根・2名・1泊・3万円以下）

```
https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426?applicationId=bf17fc69-ec1b-45c9-914e-0885d491a2c7&accessKey=pk_egccPTCYNEBYbQAQPKjhzy9qzp4VYlHO03c0kz6o8g9&affiliateId=53374f89.9deecdc4.53374f8a.b14caea3&format=json&latitude=35.2327&longitude=139.1069&searchRadius=3&datumType=1&checkinDate=20260601&checkoutDate=20260602&adultNum=2&maxCharge=30000&hits=5&sort=standard
```

---

## 2. レスポンス構造

実際のAPIレスポンス（1ホテル分の抜粋）:

```json
{
  "hotel": [
    {
      "hotelBasicInfo": {
        "hotelNo": 19684,
        "hotelName": "箱根湯本温泉　ホテル　おかだ",
        "hotelMinCharge": 11000,
        "latitude": 35.22668083,
        "longitude": 139.0922494,
        "reviewCount": 1575,
        "reviewAverage": 4.38,
        "hotelInformationUrl": "https://hb.afl.rakuten.co.jp/...",
        "hotelImageUrl": "https://img.travel.rakuten.co.jp/share/HOTEL/19684/19684.jpg",
        "nearestStation": "箱根湯本",
        "access": "箱根湯本駅～徒歩２０分..."
      }
    },
    {
      "roomInfo": [
        {
          "roomBasicInfo": {
            "roomName": "【一般客室】和室又は和洋室　37平米",
            "planName": "【早割７】素泊まりプラン",
            "withDinnerFlag": 0,
            "withBreakfastFlag": 0,
            "reserveUrl": "https://hb.afl.rakuten.co.jp/..."
          }
        },
        {
          "dailyCharge": {
            "stayDate": "2026-06-01",
            "rakutenCharge": 13200,
            "total": 26400,
            "chargeFlag": 0
          }
        }
      ]
    }
  ]
}
```

---

## 3. 料金フィールドの解説

### `dailyCharge` の各フィールド

| フィールド | 型 | 意味 |
|---|---|---|
| `stayDate` | string | 宿泊日（`"2026-06-01"` 形式） |
| `rakutenCharge` | int | **chargeFlag に依存（下記参照）** |
| `total` | int | **1室あたりの合計料金**（chargeFlag 関係なく常に1室料金） |
| `chargeFlag` | int | 0 = `rakutenCharge` が大人1名あたり料金 / 1 = 1室あたり料金 |

### `chargeFlag` による `rakutenCharge` の意味の違い

```
chargeFlag = 0（大人1名あたり料金）の場合:
  rakutenCharge = 13,200円  ← 1人あたりの1泊料金
  total         = 26,400円  ← 1室の合計（13,200 × 2人）

chargeFlag = 1（1室あたり料金）の場合:
  rakutenCharge = 26,400円  ← 1室の料金（= total と同じ）
  total         = 26,400円  ← 1室の合計
```

### ⚠️ 重要

**`total` は chargeFlag に関わらず常に「1室あたりの1泊料金」** を表す。
`chargeFlag` を気にせず `total` を使えば安全。

---

## 4. 1人あたりの料金計算

### 計算式

```
1人あたりの1泊料金 = total ÷ adultNum
```

### 実例（上記レスポンスの場合）

```
total = 26,400円（1室の料金）
adultNum = 2名

1人あたり = 26,400 ÷ 2 = 13,200円/人・泊
```

### 複数プランが返ってくる場合

1つのホテルに複数の `roomInfo` エントリ（プラン）が含まれることがある。
最安値を選ぶ場合は `total` の最小値を採用する:

```python
min_price = min(
    stay["total"]
    for room in room_info_list
    for stay in room.get("dailyCharge", {}).get("stayDate", [])
    if isinstance(stay.get("total"), (int, float)) and stay["total"] > 0
)
per_person = min_price // adult_num
```

---

## 5. Python での実装例

```python
import os
import requests

def get_hotel_prices(lat: float, lng: float, checkin: str, checkout: str,
                     adult_num: int, max_charge: int) -> list[dict]:
    """
    VacantHotelSearch で宿泊候補と1人あたり料金を取得する。

    Args:
        checkin:    チェックイン日（"YYYY-MM-DD"）
        checkout:   チェックアウト日（"YYYY-MM-DD"）
        adult_num:  大人の人数
        max_charge: 1室1泊あたりの上限料金（円）

    Returns:
        [{"name": str, "per_person_jpy": int, "total_jpy": int,
          "rating": float|None, "url": str}, ...]
    """
    params = {
        "applicationId": os.environ["RAKUTEN_APPLICATION_ID"],
        "accessKey":     os.environ["RAKUTEN_ACCESS_KEY"],
        "format":        "json",
        "latitude":      lat,
        "longitude":     lng,
        "searchRadius":  3,
        "datumType":     1,           # WGS84 度単位（省略不可）
        "checkinDate":   checkin.replace("-", ""),   # "2026-06-01" → "20260601"
        "checkoutDate":  checkout.replace("-", ""),
        "adultNum":      adult_num,
        "maxCharge":     max_charge,
        "hits":          5,
        "sort":          "standard",
    }

    resp = requests.get(
        "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426",
        params=params,
        headers={"Referer": os.environ.get("SITE_BASE_URL", "https://example.com/")},
        timeout=8,
    )
    resp.raise_for_status()

    results = []
    for entry in resp.json().get("hotels", []):
        hotel_list = entry.get("hotel", [])

        # ホテル基本情報
        basic_info = {}
        rating = None
        room_info_list = []

        for item in hotel_list:
            if "hotelBasicInfo" in item:
                basic_info = item["hotelBasicInfo"]
            elif "hotelRatingInfo" in item:
                ra = item["hotelRatingInfo"].get("reviewAverage")
                if isinstance(ra, (int, float)) and 0 <= ra <= 5:
                    rating = float(ra)
            elif "roomInfo" in item:
                room_info_list = item["roomInfo"]

        name = basic_info.get("hotelName")
        url = basic_info.get("hotelInformationUrl")
        if not name:
            continue

        # 最安値プランの1室料金を取得（total を使う）
        min_total = None
        for room in room_info_list:
            daily = room.get("dailyCharge", {})
            # stayDate は dict（1泊）または list（複数泊）
            stay_dates = daily.get("stayDate", [])
            if isinstance(stay_dates, dict):
                stay_dates = [stay_dates]
            for stay in stay_dates:
                total = stay.get("total")
                if isinstance(total, (int, float)) and total > 0:
                    if min_total is None or int(total) < min_total:
                        min_total = int(total)

        if min_total is None:
            continue

        results.append({
            "name":           name,
            "total_jpy":      min_total,                  # 1室1泊の料金
            "per_person_jpy": min_total // adult_num,     # 1人あたり
            "rating":         rating,
            "url":            url,
        })

    return results


# 使用例
if __name__ == "__main__":
    hotels = get_hotel_prices(
        lat=35.2327, lng=139.1069,
        checkin="2026-06-01", checkout="2026-06-02",
        adult_num=2, max_charge=30000,
    )
    for h in hotels:
        print(f"{h['name']}")
        print(f"  1室: ¥{h['total_jpy']:,}  |  1人あたり: ¥{h['per_person_jpy']:,}")
        print(f"  評価: {h['rating'] or '—'}  |  URL: {h['url']}")
        print()
```

### 実行結果の例

```
箱根湯本温泉　ホテル　おかだ
  1室: ¥26,400  |  1人あたり: ¥13,200
  評価: 4.38  |  URL: https://hb.afl.rakuten.co.jp/...

箱根湯本温泉　ホテルおくゆも
  1室: ¥19,420  |  1人あたり: ¥9,710
  評価: 4.12  |  URL: https://hb.afl.rakuten.co.jp/...
```

---

## 6. 宿泊日数ごとの料金取得（複数泊）

2泊以上の場合、`stayDate` が配列になり日ごとの料金が入る。

```
1泊: checkoutDate = checkinDate + 1日
2泊: checkoutDate = checkinDate + 2日
3泊: checkoutDate = checkinDate + 3日
```

複数泊の場合の `total` は「1泊あたりの料金」ではなく**その宿泊日の料金**。
宿泊日数分の合計を計算するには各 `stayDate` の `total` を合計する。

```python
# 複数泊の合計料金
total_stay = sum(stay["total"] for stay in stay_dates)
per_person_total = total_stay // adult_num
nights = len(stay_dates)
per_person_per_night = per_person_total // nights
```

---

## 7. 注意事項

- **`datumType=1` は省略不可**: 省略すると緯度経度が日本測地系・秒単位として解釈され、全く別の場所を検索してしまう
- **`checkinDate` は YYYYMMDD 形式**: `"2026-06-01"` ではなく `"20260601"` で送る
- **`maxCharge` は1室あたりの上限**: 1人あたりではない点に注意
- **`total` を使う**: `rakutenCharge` は `chargeFlag` によって意味が変わるため、常に `total`（1室合計）を基準にする
- **`hotelMinCharge`（SimpleHotelSearch の値）との違い**: `hotelMinCharge` は「目安の最安値」で日付・空室・人数を考慮しない参考値。実際の料金は VacantHotelSearch の `total` を使う
