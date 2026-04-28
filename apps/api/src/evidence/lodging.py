"""楽天トラベル SimpleHotelSearch API から宿泊候補を取得する。

エンドポイント: Travel/SimpleHotelSearch/20170426
ドキュメント: https://webservice.rakuten.co.jp/documentation/simple-hotel-search

環境変数:
    RAKUTEN_APPLICATION_ID  必須
    RAKUTEN_ACCESS_KEY      必須（新 API から必須化）
    RAKUTEN_AFFILIATE_ID    任意（アフィリエイトリンク生成用）
    SITE_BASE_URL           任意（Referer ヘッダー用、登録アプリ URL と一致させること）

注意:
    SimpleHotelSearch は施設情報のみ返す（空室・料金検索は VacantHotelSearch）。
    価格は hotelMinCharge（1部屋1泊最安値の目安）を使用する。
    緯度経度は datumType=1（世界測地系 WGS84、度単位）で送受信する。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .pack import LodgingOption

logger = logging.getLogger(__name__)

_ENDPOINT = "https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20170426"
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
    """楽天トラベル API で宿泊候補を取得して LodgingOption リストで返す。

    Args:
        region: 地域名（ログ用）
        checkin_date: チェックイン日（YYYY-MM-DD）※施設検索には使用しない
        checkout_date: チェックアウト日（YYYY-MM-DD）※施設検索には使用しない
        adult_num: 大人人数 ※施設検索には使用しない
        max_charge_per_night: 1泊上限金額（円）— 結果をクライアント側でフィルタ
        lat: 緯度（WGS84 度単位、必須）
        lng: 経度（WGS84 度単位、必須）

    Returns:
        LodgingOption のリスト（0 件もあり得る）

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

    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

    params: dict[str, Any] = {
        "applicationId": app_id,
        "accessKey": access_key,
        "format": "json",
        "latitude": lat,
        "longitude": lng,
        "searchRadius": 3,      # 半径 3km
        "datumType": 1,         # WGS84 度単位（省略時は日本測地系・秒単位になり別場所を検索）
        "hits": _MAX_RESULTS,
        "sort": "standard",     # 近い順
        "responseType": "middle",
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id

    site_base_url = os.environ.get("SITE_BASE_URL", "https://hackathon-2026-04-13.vercel.app/")
    headers = {"Referer": site_base_url}

    logger.info(
        "rakuten lodging search: region=%s lat=%.4f lng=%.4f max_charge=%d",
        region, lat, lng, max_charge_per_night,
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

    # レスポンス構造（formatVersion=1 デフォルト）:
    # {"hotels": [{"hotel": [{"hotelBasicInfo": {...}}, {"hotelRatingInfo": {...}}]}, ...]}
    raw_hotels = data.get("hotels", [])
    logger.info("rakuten lodging: %d 件取得 (max_charge フィルタ前)", len(raw_hotels))

    results = []
    for entry in raw_hotels:
        opt = _to_lodging_option(entry)
        if opt is None:
            continue
        # 価格上限フィルタ（SimpleHotelSearch は API 側で maxCharge 指定不可のため client 側で絞る）
        if opt.price_jpy_per_night <= max_charge_per_night:
            results.append(opt)

    logger.info("rakuten lodging: %d 件（max_charge=%d 以下）", len(results), max_charge_per_night)
    return results


def _to_lodging_option(hotel_entry: dict) -> LodgingOption | None:
    """楽天 SimpleHotelSearch のレスポンスエントリを LodgingOption に変換する。

    formatVersion=1（デフォルト）の構造:
        hotel_entry = {"hotel": [{"hotelBasicInfo": {...}}, {"hotelRatingInfo": {...}}]}
    """
    try:
        hotel_list = hotel_entry.get("hotel", [])
        if not hotel_list:
            return None

        # hotelBasicInfo を探す
        info: dict = {}
        for item in hotel_list:
            if "hotelBasicInfo" in item:
                info = item["hotelBasicInfo"]
                break
        if not info:
            return None

        name = info.get("hotelName", "")
        price = info.get("hotelMinCharge")  # 1部屋1泊最安値の目安（税・サービス料込）
        hotel_lat = info.get("latitude")
        hotel_lng = info.get("longitude")
        url = info.get("hotelInformationUrl") or info.get("planListUrl")
        hotel_id = str(info.get("hotelNo", ""))

        # Phase 3 polish 案 D 第 3 段 (2026-04-28): hotelRatingInfo.reviewAverage を抽出
        # して Evidence Modal の「評価」表示を「~ 不明」から数値に。0.0〜5.0 の範囲、
        # 取れなかった場合 None。formatVersion=1 では hotel_entry["hotel"][1] 等の別 entry
        # に hotelRatingInfo として配置される。
        review_average: float | None = None
        for item in hotel_list:
            if "hotelRatingInfo" in item:
                ra = item["hotelRatingInfo"].get("reviewAverage")
                if isinstance(ra, (int, float)) and 0 <= ra <= 5:
                    review_average = float(ra)
                break

        if not name or price is None:
            return None

        place_id = f"rakuten_{hotel_id}" if hotel_id else f"rakuten_{name[:20]}"

        return LodgingOption(
            place_id=place_id,
            name=name,
            price_jpy_per_night=int(price),
            lat=float(hotel_lat) if hotel_lat is not None else None,
            lng=float(hotel_lng) if hotel_lng is not None else None,
            url=url,
            rating=review_average,
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning("rakuten hotel entry parse error: %s — %s", e, hotel_entry)
        return None
