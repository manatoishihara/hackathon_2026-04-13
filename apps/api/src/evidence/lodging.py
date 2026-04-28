<<<<<<< HEAD
"""楽天トラベル施設検索 API から宿泊候補を取得する。
=======
"""楽天トラベル SimpleHotelSearch API から宿泊候補を取得する。
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

公式ドキュメント (2026-04-28 確認):
https://webservice.rakuten.co.jp/documentation/simple-hotel-search

エンドポイント: https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20170426
(旧 app.rakuten.co.jp ドメインからは 2026-04 時点で移行されている)

環境変数:
<<<<<<< HEAD
    RAKUTEN_APPLICATION_ID  必須 (アプリ ID、18-19 桁数字)
    RAKUTEN_ACCESS_KEY      必須【NEW】 (アクセスキー、新仕様で必須化)
    RAKUTEN_AFFILIATE_ID    任意 (アフィリエイトリンク生成用)

検索方式:
    - 公式 API は keyword 検索を提供しないので、本クライアントは「region → lat/lng
      (Geocoding API) → 半径 3km 圏内の lodging 検索」フローを採用する
    - searchRadius は API 仕様で 0.1〜3.0 km、本クライアントは 3.0 km 固定
    - datumType=1 (世界測地系・度) で WGS84 lat/lng をそのまま渡す
    - format=json + formatVersion=2 で JSON アクセスを `items[0].itemName` 形式に簡素化
    - SimpleHotelSearch は施設情報のみ返すので、checkinDate/checkoutDate/adultNum/maxCharge
      は API spec 上未対応 (空室検索は別 API VacantHotelSearch、本クライアントは spec 準拠)

Phase 3 polish 案 D 対応 (2026-04-28):
旧コードは applicationId のみで keyword 検索していたが、これは API spec に存在しない
パラメータで実際には全国検索 → 区分 reject されていた。新コードで spec 準拠に修正。
=======
    RAKUTEN_APPLICATION_ID  必須
    RAKUTEN_ACCESS_KEY      必須（新 API から必須化）
    RAKUTEN_AFFILIATE_ID    任意（アフィリエイトリンク生成用）
    SITE_BASE_URL           任意（Referer ヘッダー用、登録アプリ URL と一致させること）

注意:
    SimpleHotelSearch は施設情報のみ返す（空室・料金検索は VacantHotelSearch）。
    価格は hotelMinCharge（1部屋1泊最安値の目安）を使用する。
    緯度経度は datumType=1（世界測地系 WGS84、度単位）で送受信する。
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .pack import LodgingOption

logger = logging.getLogger(__name__)

_ENDPOINT = "https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20170426"
<<<<<<< HEAD
_TIMEOUT_SEC = 5
_MAX_RESULTS = 5  # LLM プロンプトに載せる最大件数 (API 仕様上は 1〜30)
_SEARCH_RADIUS_KM = 3.0  # API 仕様上の上限
_DATUM_TYPE_WGS84 = 1
=======
_TIMEOUT_SEC = 8
_MAX_RESULTS = 5  # LLM プロンプトに載せる最大件数
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072


class RakutenLodgingError(Exception):
    """楽天トラベル API 呼び出し失敗。"""


def fetch_lodging_options(
<<<<<<< HEAD
    lat: float,
    lng: float,
    *,
    search_radius_km: float = _SEARCH_RADIUS_KM,
    application_id: str | None = None,
    access_key: str | None = None,
    affiliate_id: str | None = None,
=======
    region: str,
    checkin_date: str,
    checkout_date: str,
    adult_num: int,
    max_charge_per_night: int,
    lat: float | None = None,
    lng: float | None = None,
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072
) -> list[LodgingOption]:
    """楽天トラベル API で緯度経度ベースの宿泊候補を取得して LodgingOption リストで返す。

    Args:
<<<<<<< HEAD
        lat: 検索中心の緯度 (世界測地系 WGS84、度単位)。
        lng: 検索中心の経度 (世界測地系 WGS84、度単位)。
        search_radius_km: 検索半径 (km、0.1〜3.0)。デフォルト 3.0 (上限)。
        application_id: 明示指定する場合。省略時は RAKUTEN_APPLICATION_ID 環境変数。
        access_key: 明示指定する場合。省略時は RAKUTEN_ACCESS_KEY 環境変数。
        affiliate_id: 明示指定する場合。省略時は RAKUTEN_AFFILIATE_ID 環境変数 (任意)。
=======
        region: 地域名（ログ用）
        checkin_date: チェックイン日（YYYY-MM-DD）※施設検索には使用しない
        checkout_date: チェックアウト日（YYYY-MM-DD）※施設検索には使用しない
        adult_num: 大人人数 ※施設検索には使用しない
        max_charge_per_night: 1泊上限金額（円）— 結果をクライアント側でフィルタ
        lat: 緯度（WGS84 度単位、必須）
        lng: 経度（WGS84 度単位、必須）
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

    Returns:
        LodgingOption のリスト (0 件もあり得る)。

    Raises:
        RakutenLodgingError: API 呼び出し失敗 / 認証情報不足 / spec 違反。
    """
    app_id = application_id or os.environ.get("RAKUTEN_APPLICATION_ID")
    if not app_id:
        raise RakutenLodgingError("RAKUTEN_APPLICATION_ID が未設定です")

<<<<<<< HEAD
    acc_key = access_key or os.environ.get("RAKUTEN_ACCESS_KEY")
    if not acc_key:
        raise RakutenLodgingError(
            "RAKUTEN_ACCESS_KEY が未設定です "
            "(新仕様で必須化、楽天ウェブサービス アプリ詳細ページで確認)"
        )

    aff_id = affiliate_id or os.environ.get("RAKUTEN_AFFILIATE_ID", "")

    # API 仕様: searchRadius は 0.1〜3.0、小数点以下 1 桁まで
    if not (0.1 <= search_radius_km <= 3.0):
        raise RakutenLodgingError(
            f"searchRadius {search_radius_km} は楽天 API の許容範囲 (0.1〜3.0) 外"
        )

    params: dict[str, Any] = {
        "applicationId": app_id,
        "accessKey": acc_key,
        "format": "json",
        "formatVersion": 2,
        "latitude": lat,
        "longitude": lng,
        "searchRadius": round(search_radius_km, 1),
        "datumType": _DATUM_TYPE_WGS84,
        "hits": _MAX_RESULTS,
        "sort": "standard",  # 緯度経度検索時は近い順
=======
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
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072
    }
    if aff_id:
        params["affiliateId"] = aff_id

    site_base_url = os.environ.get("SITE_BASE_URL", "https://hackathon-2026-04-13.vercel.app/")
    headers = {"Referer": site_base_url}

    logger.info(
<<<<<<< HEAD
        "rakuten lodging search: lat=%.6f lng=%.6f radius=%.1fkm hits=%d",
        lat, lng, search_radius_km, _MAX_RESULTS,
=======
        "rakuten lodging search: region=%s lat=%.4f lng=%.4f max_charge=%d",
        region, lat, lng, max_charge_per_night,
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072
    )

    try:
        resp = requests.get(_ENDPOINT, params=params, headers=headers, timeout=_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as e:
<<<<<<< HEAD
        # error response 本文を log に残す (400 wrong_parameter / 404 not_found /
        # 429 too_many_requests / 500 system_error / 503 service_unavailable の判別に必要)
=======
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072
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


<<<<<<< HEAD
def _to_lodging_option(hotel_entry: Any) -> LodgingOption | None:
    """楽天 API の hotel エントリを LodgingOption に変換する。

    formatVersion=2 でも `hotels[i]` は配列 ([hotelBasicInfo, hotelRatingInfo, ...] 形式)
    で返ってくる。formatVersion=2 はネストしたオブジェクト省略の最適化のみで、配列構造は
    維持される (公式 docs の formatVersion 説明参照)。
    """
    try:
        # hotel_entry は [{"hotelBasicInfo": {...}}, {"hotelRatingInfo": {...}}, ...] 形式
        if not isinstance(hotel_entry, list) or not hotel_entry:
            return None
        # formatVersion=2 では各要素から直接 key 引けるが、念のため両形式に対応
        info = None
        for entry in hotel_entry:
            if not isinstance(entry, dict):
                continue
            if "hotelBasicInfo" in entry:
                info = entry["hotelBasicInfo"]
                break
            # formatVersion=2 で 1 段省略形式の場合
            if "hotelName" in entry:
                info = entry
                break
        if info is None:
            return None

        name = info.get("hotelName", "")
        # SimpleHotelSearch は宿泊日付 / プラン情報を返さないので、
        # hotelMinCharge (1 部屋 1 泊あたり、税・サービス料込みの最安値の目安) を使う。
        price = info.get("hotelMinCharge")
        lat = info.get("latitude")
        lng = info.get("longitude")
=======
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
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072
        url = info.get("hotelInformationUrl") or info.get("planListUrl")
        hotel_id = str(info.get("hotelNo", ""))

        if not name or price is None:
            return None

<<<<<<< HEAD
        # place_id は楽天 hotel ID をプレフィックスで代用 (Google Places ID ではない)
        hotel_id = str(info.get("hotelNo", ""))
=======
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072
        place_id = f"rakuten_{hotel_id}" if hotel_id else f"rakuten_{name[:20]}"

        return LodgingOption(
            place_id=place_id,
            name=name,
            price_jpy_per_night=int(price),
            lat=float(hotel_lat) if hotel_lat is not None else None,
            lng=float(hotel_lng) if hotel_lng is not None else None,
            url=url,
        )
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning("rakuten hotel entry parse error: %s — %s", e, hotel_entry)
        return None
