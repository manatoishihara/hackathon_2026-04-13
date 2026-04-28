"""`apps/api/src/evidence/opening_hours.py` のユニットテスト（Phase 1.3d Branch 0）。

Google Places (New) API の `regularOpeningHours.weekdayDescriptions` は日本語文字列で、
例: `["月曜日: 9時00分～17時00分", "火曜日: 定休日", ...]`。これを構造化して LLM validator が
厳密に営業時間判定できるようにする。

parse 失敗時は該当曜日を `unknown_days` に登録し、validator 側でその曜日の検証をスキップする
（block しない、計画書 v3 参照）。
"""

from __future__ import annotations

import pytest

from src.evidence.opening_hours import (
    OpeningHoursParseResult,
    parse_weekday_descriptions,
)
from src.evidence.pack import OpeningHoursSlot


def test_parse_single_slot_monday_morning_to_evening():
    descriptions = ["月曜日: 9時00分～17時00分"]
    result = parse_weekday_descriptions(descriptions)
    assert isinstance(result, OpeningHoursParseResult)
    assert result.slots == [
        OpeningHoursSlot(day_of_week=0, open_hhmm="09:00", close_hhmm="17:00"),
    ]
    assert result.unknown_days == []


def test_parse_all_week():
    descriptions = [
        "月曜日: 9時00分～18時00分",
        "火曜日: 9時00分～18時00分",
        "水曜日: 9時00分～18時00分",
        "木曜日: 9時00分～18時00分",
        "金曜日: 9時00分～18時00分",
        "土曜日: 10時00分～20時00分",
        "日曜日: 10時00分～20時00分",
    ]
    result = parse_weekday_descriptions(descriptions)
    assert len(result.slots) == 7
    # 月曜は 0、日曜は 6
    assert result.slots[0].day_of_week == 0
    assert result.slots[6].day_of_week == 6
    assert result.slots[5].open_hhmm == "10:00"  # 土曜
    assert result.unknown_days == []


def test_parse_closed_day():
    descriptions = ["月曜日: 定休日"]
    result = parse_weekday_descriptions(descriptions)
    # 定休日は slot を生成しない、unknown でもない（＝明示的に閉まっている）
    assert result.slots == []
    assert result.unknown_days == []


def test_parse_24_hour_operation():
    descriptions = ["月曜日: 24 時間営業"]
    result = parse_weekday_descriptions(descriptions)
    assert len(result.slots) == 1
    assert result.slots[0].day_of_week == 0
    assert result.slots[0].open_hhmm == "00:00"
    assert result.slots[0].close_hhmm == "23:59"


def test_parse_24_hour_operation_without_space():
    descriptions = ["月曜日: 24時間営業"]
    result = parse_weekday_descriptions(descriptions)
    assert len(result.slots) == 1
    assert result.slots[0].open_hhmm == "00:00"


def test_parse_split_hours_lunch_and_dinner():
    """ランチ / ディナー分割（間に休憩）→ slot 2 件"""
    descriptions = ["月曜日: 11時00分～14時30分、17時00分～22時00分"]
    result = parse_weekday_descriptions(descriptions)
    assert len(result.slots) == 2
    assert result.slots[0].day_of_week == 0
    assert result.slots[0].open_hhmm == "11:00"
    assert result.slots[0].close_hhmm == "14:30"
    assert result.slots[1].day_of_week == 0
    assert result.slots[1].open_hhmm == "17:00"
    assert result.slots[1].close_hhmm == "22:00"


def test_parse_unparseable_returns_unknown_day():
    """parse できない曜日は unknown_days に登録される（validator でスキップされる）"""
    descriptions = ["月曜日: 店主の気分によります"]
    result = parse_weekday_descriptions(descriptions)
    assert result.slots == []
    assert result.unknown_days == [0]


def test_parse_mixed_known_and_unknown():
    descriptions = [
        "月曜日: 9時00分～18時00分",
        "火曜日: 謎のフォーマット",
        "水曜日: 定休日",
    ]
    result = parse_weekday_descriptions(descriptions)
    assert len(result.slots) == 1
    assert result.slots[0].day_of_week == 0
    assert result.unknown_days == [1]


def test_parse_empty_list():
    result = parse_weekday_descriptions([])
    assert result.slots == []
    assert result.unknown_days == []


def test_parse_unknown_day_name_is_unknown():
    """曜日名が認識できないレコードは unknown（parse 不能扱い）"""
    descriptions = ["Martes: 9時00分～18時00分"]  # スペイン語
    result = parse_weekday_descriptions(descriptions)
    assert result.slots == []
    # 曜日すら特定できないので unknown_days にも載せない（誰の曜日か不明）
    assert result.unknown_days == []


def test_opening_hours_slot_validates_hhmm_format():
    with pytest.raises(Exception):  # Pydantic ValidationError
        OpeningHoursSlot(day_of_week=0, open_hhmm="25:00", close_hhmm="17:00")


def test_opening_hours_slot_day_of_week_range():
    with pytest.raises(Exception):
        OpeningHoursSlot(day_of_week=7, open_hhmm="09:00", close_hhmm="17:00")
