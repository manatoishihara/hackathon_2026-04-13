"""楽天トラベル API から宿泊候補を取得する。

エンドポイント: Travel/SimpleHotelSearch/20170426
ドキュメント: https://webservice.rakuten.co.jp/documentation/simple-hotel-search

環境変数:
    RAKUTEN_APPLICATION_ID  必須
    RAKUTEN_AFFILIATE_ID    任意（アフィリエイトリンク生成用）
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .pack import LodgingOption

logger = logging.getLogger(__name__)

_ENDPOINT = "https://app.rakuten.co.jp/services/api/Travel/SimpleHotelSearch/20170426"
_TIMEOUT_SEC = 5
_MAX_RESULTS = 5  # LLM プロンプトに載せる最大件数


class RakutenLodgingError(Exception):
    """楽天トラベル API 呼び出し失敗。"""


def fetch_lodging_options(
    region: str,
    checkin_date: str,
    checkout_date: str,
    adult_num: int,
    max_charge_per_night: int,
) -> list[LodgingOption]:
    """楽天トラベル API で宿泊候補を取得して LodgingOption リストで返す。

    Args:
        region: 検索キーワード（例: "箱根"）
        checkin_date: チェックイン日（YYYY-MM-DD）
        checkout_date: チェックアウト日（YYYY-MM-DD）
        adult_num: 大人人数
        max_charge_per_night: 1泊1室あたりの上限金額（円）

    Returns:
        LodgingOption のリスト（0 件もあり得る）

    Raises:
        RakutenLodgingError: API 呼び出し失敗
    """
    app_id = os.environ.get("RAKUTEN_APPLICATION_ID")
    if not app_id:
        raise RakutenLodgingError("RAKUTEN_APPLICATION_ID が未設定です")

    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

    params: dict[str, Any] = {
        "applicationId": app_id,
        "format": "json",
        "keyword": region,
        "checkinDate": checkin_date,
        "checkoutDate": checkout_date,
        "adultNum": adult_num,
        "maxCharge": max_charge_per_night,
        "hits": _MAX_RESULTS,
        "sort": "standard",
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id

    logger.info(
        "rakuten lodging search: region=%s checkin=%s checkout=%s adults=%d max_charge=%d",
        region, checkin_date, checkout_date, adult_num, max_charge_per_night,
    )

    try:
        resp = requests.get(_ENDPOINT, params=params, timeout=_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise RakutenLodgingError(f"楽天トラベル API リクエスト失敗: {e}") from e

    hotels = data.get("hotels", [])
    logger.info("rakuten lodging: %d 件取得", len(hotels))

    return [_to_lodging_option(h) for h in hotels if _to_lodging_option(h) is not None]


def _to_lodging_option(hotel_entry: dict) -> LodgingOption | None:
    """楽天 API の hotel エントリを LodgingOption に変換する。"""
    try:
        info = hotel_entry[0]["hotelBasicInfo"]
        plan = hotel_entry[1]["roomInfo"][0]["dailyCharge"] if len(hotel_entry) > 1 else {}

        name = info.get("hotelName", "")
        price = plan.get("stayDate", {}).get("rakutenCharge") or info.get("hotelMinCharge")
        lat = info.get("latitude")
        lng = info.get("longitude")
        url = info.get("hotelInformationUrl") or info.get("planListUrl")

        if not name or price is None:
            return None

        # place_id は楽天 hotel ID をプレフィックスで代用（Google Places ID ではない）
        hotel_id = str(info.get("hotelNo", ""))
        place_id = f"rakuten_{hotel_id}" if hotel_id else f"rakuten_{name[:20]}"

        return LodgingOption(
            place_id=place_id,
            name=name,
            price_jpy_per_night=int(price),
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
            url=url,
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning("rakuten hotel entry parse error: %s — %s", e, hotel_entry)
        return None
