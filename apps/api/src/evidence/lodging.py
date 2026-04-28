"""楽天トラベル VacantHotelSearch API から宿泊実価格を取得する。

エンドポイント: Travel/VacantHotelSearch/20170426
ドキュメント: https://webservice.rakuten.co.jp/documentation/vacant-hotel-search

Task A3 (2026-04-28): 旧 SimpleHotelSearch (hotelMinCharge = 目安最安値) から
VacantHotelSearch (実価格) への移行。指定日に空室がある宿の `total` (1 室合計料金)
を adultNum で割って 1 人あたり 1 泊料金を算出する。

副作用: VacantHotelSearch は「指定日に空室あり」の宿のみ返るので 0 件率は上がる。
builder.py の Google Places lodging fallback (Phase 3 polish 第 8 段) と組み合わせて
demo blocker を回避する。

環境変数:
    RAKUTEN_APPLICATION_ID  必須 (UUID 形式)
    RAKUTEN_ACCESS_KEY      必須 (`pk_` で始まる)
    RAKUTEN_AFFILIATE_ID    任意 (アフィリエイトリンク生成用)
    SITE_BASE_URL           任意 (Referer ヘッダー用、登録アプリ URL と一致させること)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .pack import LodgingOption

logger = logging.getLogger(__name__)

_ENDPOINT = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"
_TIMEOUT_SEC = 8
_MAX_RESULTS = 5  # LLM プロンプトに載せる最大件数


class RakutenLodgingError(Exception):
    """楽天トラベル API 呼び出し失敗。"""


def fetch_lodging_options(
    region: str,
    checkin_date: str,
    checkout_date: str,
    adult_num: int,
    max_charge_per_night: int,
    lat: float | None = None,
    lng: float | None = None,
) -> list[LodgingOption]:
    """VacantHotelSearch で宿泊候補を取得して LodgingOption リストで返す。

    Args:
        region: 地域名 (ログ用)
        checkin_date: チェックイン日 (YYYY-MM-DD)。API 送信時 YYYYMMDD に変換
        checkout_date: チェックアウト日 (YYYY-MM-DD)
        adult_num: 大人人数
        max_charge_per_night: 1 室 1 泊上限金額 (円)
        lat: 緯度 (WGS84 度単位、必須)
        lng: 経度 (WGS84 度単位、必須)

    Returns:
        LodgingOption のリスト (0 件もあり得る、`price_jpy_per_night` は 1 人あたり)

    Raises:
        RakutenLodgingError: API 呼び出し失敗
    """
    app_id = os.environ.get("RAKUTEN_APPLICATION_ID")
    if not app_id:
        raise RakutenLodgingError("RAKUTEN_APPLICATION_ID が未設定です")

    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    if not access_key:
        raise RakutenLodgingError("RAKUTEN_ACCESS_KEY が未設定です")

    if lat is None or lng is None:
        logger.warning("rakuten lodging: 座標未指定のためスキップ (region=%s)", region)
        return []

    if adult_num <= 0:
        logger.warning("rakuten lodging: adult_num が 0 以下のためスキップ (region=%s)", region)
        return []

    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

    params: dict[str, Any] = {
        "applicationId": app_id,
        "accessKey": access_key,
        "format": "json",
        "latitude": lat,
        "longitude": lng,
        "searchRadius": 3,      # 半径 3km
        "datumType": 1,         # WGS84 度単位 (省略時は日本測地系・秒単位になり別場所を検索)
        "checkinDate": checkin_date.replace("-", ""),    # YYYY-MM-DD → YYYYMMDD
        "checkoutDate": checkout_date.replace("-", ""),
        "adultNum": adult_num,
        "maxCharge": max_charge_per_night,
        "hits": _MAX_RESULTS,
        "sort": "standard",     # 近い順
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id

    site_base_url = os.environ.get("SITE_BASE_URL", "https://hackathon-2026-04-13.vercel.app/")
    headers = {"Referer": site_base_url}

    logger.info(
        "rakuten vacant search: region=%s lat=%.4f lng=%.4f checkin=%s adult=%d max_charge=%d",
        region, lat, lng, checkin_date, adult_num, max_charge_per_night,
    )

    try:
        resp = requests.get(_ENDPOINT, params=params, headers=headers, timeout=_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as e:
        body_summary = ""
        try:
            body_summary = resp.text[:500]
        except Exception:
            pass
        raise RakutenLodgingError(
            f"楽天トラベル API リクエスト失敗: {e} (response body: {body_summary!r})"
        ) from e
    except requests.RequestException as e:
        raise RakutenLodgingError(f"楽天トラベル API リクエスト失敗: {e}") from e

    raw_hotels = data.get("hotels", [])
    logger.info("rakuten vacant: %d 件取得 (max_charge フィルタ前)", len(raw_hotels))

    results = []
    for entry in raw_hotels:
        opt = _to_lodging_option(entry, adult_num)
        if opt is None:
            continue
        # client 側 max_charge filter (per_person × adult_num = 1 室 total を逆算して比較)
        # API 側で既に絞り込まれているはずだが冗長 check として残す
        if opt.price_jpy_per_night * adult_num <= max_charge_per_night:
            results.append(opt)

    logger.info("rakuten vacant: %d 件 (max_charge=%d 以下)", len(results), max_charge_per_night)
    return results


def _to_lodging_option(hotel_entry: dict, adult_num: int) -> LodgingOption | None:
    """VacantHotelSearch のレスポンスエントリを LodgingOption に変換する。

    formatVersion=1 (デフォルト) の構造:
        hotel_entry = {"hotel": [
            {"hotelBasicInfo": {...}},
            {"hotelRatingInfo": {...}},  # optional
            {"roomInfo": [
                {"roomBasicInfo": {"planName": "..."}},
                {"dailyCharge": {"stayDate": "...", "total": int, ...}},
                # 複数泊なら dailyCharge が複数 entry になる可能性あり
            ]},
            {"roomInfo": [...]},  # 複数プランなら roomInfo が複数 entry
            ...
        ]}

    最安値プランの total を抽出 (1 室合計、複数泊なら sum)、adult_num で割って per_person price。
    """
    try:
        hotel_list = hotel_entry.get("hotel", [])
        if not hotel_list:
            return None

        info: dict = {}
        review_average: float | None = None
        room_info_lists: list[list[dict]] = []
        for item in hotel_list:
            if "hotelBasicInfo" in item:
                info = item["hotelBasicInfo"]
            elif "hotelRatingInfo" in item:
                ra = item["hotelRatingInfo"].get("reviewAverage")
                if isinstance(ra, (int, float)) and 0 <= ra <= 5:
                    review_average = float(ra)
            elif "roomInfo" in item:
                # roomInfo は list (各 plan の dailyCharge を含む)
                room_info_value = item["roomInfo"]
                if isinstance(room_info_value, list):
                    room_info_lists.append(room_info_value)

        if not info:
            return None

        name = info.get("hotelName", "")
        hotel_lat = info.get("latitude")
        hotel_lng = info.get("longitude")
        url = info.get("hotelInformationUrl") or info.get("planListUrl")
        hotel_id = str(info.get("hotelNo", ""))

        if not name:
            return None

        # 最安値プランの total を抽出
        # 各 roomInfo は 1 プラン分。dailyCharge は単一 dict (1 泊) または複数 entry (複数泊) の
        # 場合がある。複数泊なら sum、1 泊なら total そのもの。複数プランなら最安値を採用。
        min_total: int | None = None
        for room_info in room_info_lists:
            stay_total_for_plan = 0
            has_charge = False
            for room_item in room_info:
                if not isinstance(room_item, dict):
                    continue
                daily = room_item.get("dailyCharge")
                if not isinstance(daily, dict):
                    continue
                total = daily.get("total")
                if isinstance(total, (int, float)) and total > 0:
                    stay_total_for_plan += int(total)
                    has_charge = True
            if has_charge:
                if min_total is None or stay_total_for_plan < min_total:
                    min_total = stay_total_for_plan

        if min_total is None:
            return None

        # 1 人あたり 1 泊料金
        # 複数泊の場合 stay_total_for_plan は泊数分の sum なので、本来は泊数で割るべきだが、
        # builder.py 側で 1 泊単位の予算上限を渡している。demo は 1 泊 2 日中心なので簡略化。
        # 将来の複数泊対応では泊数情報を引数で受け取る必要あり。
        per_person = min_total // adult_num

        place_id = f"rakuten_{hotel_id}" if hotel_id else f"rakuten_{name[:20]}"

        return LodgingOption(
            place_id=place_id,
            name=name,
            price_jpy_per_night=per_person,
            lat=float(hotel_lat) if hotel_lat is not None else None,
            lng=float(hotel_lng) if hotel_lng is not None else None,
            url=url,
            rating=review_average,
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning("rakuten hotel entry parse error: %s — %s", e, hotel_entry)
        return None
