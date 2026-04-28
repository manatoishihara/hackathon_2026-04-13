"""楽天トラベル API 疎通テスト（実際の API を叩く）。

使い方:
    cd apps/api
    source .venv/bin/activate
    python scripts/test_rakuten_live.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# .env を読み込む
env_path = Path(__file__).parent.parent.parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            value = value.strip().strip("'\"")
            os.environ.setdefault(key.strip(), value)

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.evidence.lodging import RakutenLodgingError, fetch_lodging_options

def check_env():
    app_id = os.environ.get("RAKUTEN_APPLICATION_ID", "")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY", "")
    print("=" * 50)
    print("環境変数チェック")
    print(f"  RAKUTEN_APPLICATION_ID : {'✅ ' + app_id[:8] + '...' if app_id else '❌ 未設定'}")
    print(f"  RAKUTEN_ACCESS_KEY     : {'✅ ' + access_key[:8] + '...' if access_key else '❌ 未設定'}")
    print("=" * 50)
    return bool(app_id) and bool(access_key)

def test_search(region: str, lat: float, lng: float, label: str):
    print(f"\n🔍 {label}を検索中 (lat={lat}, lng={lng})...")
    try:
        results = fetch_lodging_options(
            region=region,
            checkin_date="2026-07-01",
            checkout_date="2026-07-02",
            adult_num=2,
            max_charge_per_night=30000,
            lat=lat,
            lng=lng,
        )
        if results:
            print(f"✅ {len(results)} 件取得成功！")
            for hotel in results:
                print(f"   - {hotel.name}: ¥{hotel.price_jpy_per_night:,}/泊")
                if hotel.url:
                    print(f"     URL: {hotel.url}")
        else:
            print("⚠️  0 件（エリアに対象ホテルなし、またはmax_charge低すぎの可能性）")
    except RakutenLodgingError as e:
        print(f"❌ APIエラー: {e}")

if __name__ == "__main__":
    if not check_env():
        print("\n❌ 必要な環境変数が未設定です。.env を確認してください。")
        sys.exit(1)

    # 箱根エリア（緯度経度）
    test_search("箱根", lat=35.2327, lng=139.1069, label="箱根")

    # 東京エリア
    test_search("東京", lat=35.6894, lng=139.6917, label="東京（新宿周辺）")
