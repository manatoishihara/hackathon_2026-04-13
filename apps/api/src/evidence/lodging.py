"""楽天トラベル API から宿泊候補を取得する。

利用 API:
    - VacantHotelSearch (優先): 日付・人数指定で実際の空室料金を取得
      エンドポイント: Travel/VacantHotelSearch/20170426
    - SimpleHotelSearch (フォールバック): 日付指定なしで施設情報と最安値目安を取得
      エンドポイント: Travel/SimpleHotelSearch/20170426

環境変数:
    RAKUTEN_APPLICATION_ID  必須
    RAKUTEN_ACCESS_KEY      必須（新 API から必須化）
    RAKUTEN_AFFILIATE_ID    任意（アフィリエイトリンク生成用）
    SITE_BASE_URL           任意（Referer ヘッダー用、登録アプリ URL と一致させること）

注意:
    緯度経度は datumType=1（世界測地系 WGS84、度単位）で送受信する。
    VacantHotelSearch が 0 件 or 失敗の場合、SimpleHotelSearch にフォールバックする。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .pack import LodgingOption

logger = logging.getLogger(__name__)

_VACANT_ENDPOINT = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"
_SIMPLE_ENDPOINT = "https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20170426"
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
    site_base_url = os.environ.get("SITE_BASE_URL", "https://hackathon-2026-04-13.vercel.app/")
    headers = {"Referer": site_base_url}

    common_params: dict[str, Any] = {
        "applicationId": app_id,
        "accessKey": access_key,
        "format": "json",
        "latitude": lat,
        "longitude": lng,
        "searchRadius": 3,
        "datumType": 1,
        "hits": _MAX_RESULTS,
        "sort": "standard",
    }
    if affiliate_id:
        common_params["affiliateId"] = affiliate_id

    logger.info(
        "rakuten lodging search: region=%s lat=%.4f lng=%.4f max_charge=%d checkin=%s checkout=%s adult=%d",
        region, lat, lng, max_charge_per_night, checkin_date, checkout_date, adult_num,
    )

    # VacantHotelSearch で実際の空室・料金を取得（優先）
    results = _fetch_vacant(
        common_params=common_params,
        headers=headers,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        adult_num=adult_num,
        max_charge_per_night=max_charge_per_night,
    )

    if results:
        logger.info("rakuten lodging: VacantHotelSearch で %d 件取得", len(results))
        return results

    # フォールバック: SimpleHotelSearch（日付・人数指定不要、hotelMinCharge を参考価格として使用）
    logger.info("rakuten lodging: VacantHotelSearch が 0 件 → SimpleHotelSearch にフォールバック")
    return _fetch_simple(
        common_params=common_params,
        headers=headers,
        max_charge_per_night=max_charge_per_night,
    )


def _fetch_vacant(
    common_params: dict[str, Any],
    headers: dict[str, str],
    checkin_date: str,
    checkout_date: str,
    adult_num: int,
    max_charge_per_night: int,
) -> list[LodgingOption]:
    """VacantHotelSearch で実際の空室・1泊料金を取得する。失敗時は空リストを返す。"""
    params = {
        **common_params,
        "checkinDate": checkin_date.replace("-", ""),   # YYYYMMDD 形式
        "checkoutDate": checkout_date.replace("-", ""),
        "adultNum": adult_num,
        "maxCharge": max_charge_per_night,
    }

    try:
        resp = requests.get(_VACANT_ENDPOINT, params=params, headers=headers, timeout=_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as e:
        body_summary = ""
        try:
            body_summary = resp.text[:500]
        except Exception:
            pass
        logger.warning("VacantHotelSearch 失敗: %s (body: %r)", e, body_summary)
        return []
    except requests.RequestException as e:
        logger.warning("VacantHotelSearch リクエスト失敗: %s", e)
        return []

    raw_hotels = data.get("hotels", [])
    logger.info("VacantHotelSearch: %d 件取得", len(raw_hotels))

    results = []
    for entry in raw_hotels:
        opt = _to_lodging_option_vacant(entry)
        if opt is not None:
            results.append(opt)
    return results


def _fetch_simple(
    common_params: dict[str, Any],
    headers: dict[str, str],
    max_charge_per_night: int,
) -> list[LodgingOption]:
    """SimpleHotelSearch で施設情報 + 最安値目安を取得する。"""
    params = {**common_params, "responseType": "middle"}

    try:
        resp = requests.get(_SIMPLE_ENDPOINT, params=params, headers=headers, timeout=_TIMEOUT_SEC)
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
    logger.info("SimpleHotelSearch: %d 件取得 (max_charge フィルタ前)", len(raw_hotels))

    results = []
    for entry in raw_hotels:
        opt = _to_lodging_option(entry)
        if opt is None:
            continue
        if opt.price_jpy_per_night <= max_charge_per_night:
            results.append(opt)

    logger.info("SimpleHotelSearch: %d 件（max_charge=%d 以下）", len(results), max_charge_per_night)
    return results


def _to_lodging_option_vacant(hotel_entry: dict) -> LodgingOption | None:
    """VacantHotelSearch のレスポンスエントリを LodgingOption に変換する。

    VacantHotelSearch の構造 (formatVersion=1):
        hotel_entry = {
            "hotel": [
                {"hotelBasicInfo": {...}},
                {"hotelRatingInfo": {...}},
                {"roomInfo": [{"roomBasicInfo": {...}, "dailyCharge": {"stayDate": [{"rakutenCharge": 15000, ...}]}}]},
            ]
        }
    """
    try:
        hotel_list = hotel_entry.get("hotel", [])
        if not hotel_list:
            return None

        info: dict = {}
        rating_info: dict = {}
        room_info_list: list = []

        for item in hotel_list:
            if "hotelBasicInfo" in item:
                info = item["hotelBasicInfo"]
            elif "hotelRatingInfo" in item:
                rating_info = item["hotelRatingInfo"]
            elif "roomInfo" in item:
                room_info_list = item["roomInfo"]

        if not info:
            return None

        name = info.get("hotelName", "")
        hotel_lat = info.get("latitude")
        hotel_lng = info.get("longitude")
        url = info.get("hotelInformationUrl") or info.get("planListUrl")
        hotel_id = str(info.get("hotelNo", ""))

        # VacantHotelSearch の実際の料金を取得（1泊あたりの最安値）
        # chargeFlag=0: rakutenCharge は大人1名あたりの料金 → total が1室合計
        # chargeFlag=1: rakutenCharge は1室あたりの料金（total も同じ）
        # price_jpy_per_night には「1室あたりの1泊料金」として total を使う
        price: int | None = None
        for room in room_info_list:
            daily = room.get("dailyCharge", {})
            stay_dates = daily.get("stayDate", [])
            for stay in stay_dates:
                total = stay.get("total")
                # total が取れない場合は rakutenCharge で代用
                charge = total if isinstance(total, (int, float)) and total > 0 else stay.get("rakutenCharge")
                if isinstance(charge, (int, float)) and charge > 0:
                    # 最安値の部屋タイプを採用
                    if price is None or int(charge) < price:
                        price = int(charge)

        # 部屋料金が取れなかった場合は hotelMinCharge にフォールバック
        if price is None:
            price = info.get("hotelMinCharge")

        if not name or price is None:
            return None

        review_average: float | None = None
        ra = rating_info.get("reviewAverage")
        if isinstance(ra, (int, float)) and 0 <= ra <= 5:
            review_average = float(ra)

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
        logger.warning("rakuten vacant hotel entry parse error: %s — %s", e, hotel_entry)
        return None


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
