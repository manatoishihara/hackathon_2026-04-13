"""Evidence Pack の Pydantic モデル（pack.py）のバリデーションテスト。

Codex レビューで「TransitEdge の Field 制約に対する負例テストが不足」と指摘されたのを
受けて、改ざん・仕様逸脱の検出を保証する（Phase 1.3 のサーバー Validator に加えて、
Pydantic 層の防御線が常に働いていることを確認）。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.evidence.pack import TransitEdge


def _valid_edge_kwargs() -> dict:
    return dict(
        from_place_id="A",
        to_place_id="B",
        mode="car",
        route_summary="車で約30分",
        duration_min=30,
        fare_jpy=None,
        candidate_departures=["09:00"],
    )


# ==============================
# 正常系
# ==============================


def test_valid_transit_edge():
    edge = TransitEdge(**_valid_edge_kwargs())
    assert edge.mode == "car"
    assert edge.duration_min == 30


def test_multiple_candidate_departures_allowed():
    kwargs = _valid_edge_kwargs()
    kwargs["candidate_departures"] = ["09:00", "09:15", "09:30"]
    edge = TransitEdge(**kwargs)
    assert len(edge.candidate_departures) == 3


# ==============================
# place_id の長さ制約
# ==============================


def test_from_place_id_too_long_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["from_place_id"] = "x" * 256
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


def test_empty_place_id_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["from_place_id"] = ""
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


# ==============================
# duration_min の値域
# ==============================


def test_negative_duration_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["duration_min"] = -1
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


def test_too_long_duration_rejected():
    """24h を超える duration は改ざんシグナル。"""
    kwargs = _valid_edge_kwargs()
    kwargs["duration_min"] = 1441
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


# ==============================
# fare_jpy の値域
# ==============================


def test_negative_fare_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["fare_jpy"] = -100
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


def test_unreasonably_high_fare_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["fare_jpy"] = 500_001
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


# ==============================
# route_summary の文字長
# ==============================


def test_overly_long_route_summary_rejected():
    """DoS 対策: 120 文字超は弾く。"""
    kwargs = _valid_edge_kwargs()
    kwargs["route_summary"] = "あ" * 121
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


def test_empty_route_summary_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["route_summary"] = ""
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


# ==============================
# candidate_departures のフォーマットと件数
# ==============================


def test_invalid_hhmm_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["candidate_departures"] = ["9:00"]  # ゼロパディング無し
    with pytest.raises(ValidationError, match="HH:mm"):
        TransitEdge(**kwargs)


def test_invalid_hhmm_24_hour_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["candidate_departures"] = ["24:00"]
    with pytest.raises(ValidationError, match="HH:mm"):
        TransitEdge(**kwargs)


def test_invalid_hhmm_seconds_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["candidate_departures"] = ["09:00:00"]
    with pytest.raises(ValidationError, match="HH:mm"):
        TransitEdge(**kwargs)


def test_empty_candidate_departures_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["candidate_departures"] = []
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


def test_too_many_candidate_departures_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["candidate_departures"] = [f"{h:02d}:00" for h in range(11)]  # 11 個
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)


# ==============================
# 未知フィールド拒否（_PackBase の共通設定）
# ==============================


def test_unknown_field_rejected():
    kwargs = _valid_edge_kwargs()
    kwargs["malicious_field"] = "<script>alert(1)</script>"
    with pytest.raises(ValidationError):
        TransitEdge(**kwargs)
