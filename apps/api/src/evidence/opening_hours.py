"""Google Places (New) `regularOpeningHours.weekdayDescriptions` の日本語パーサ。

入力例（languageCode=ja 指定時）:
    "月曜日: 9時00分～17時00分"
    "火曜日: 定休日"
    "水曜日: 24 時間営業"
    "木曜日: 11時00分～14時30分、17時00分～22時00分"

出力: `OpeningHoursParseResult`（slots + unknown_days）。
parse 失敗時はその曜日を `unknown_days` に登録し、validator 側でその曜日の検証をスキップする
（block しない、計画書 v3 「opening_hours parse 失敗時」参照）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .pack import OpeningHoursSlot

logger = logging.getLogger(__name__)

_JAPANESE_WEEKDAYS: dict[str, int] = {
    "月曜日": 0,
    "火曜日": 1,
    "水曜日": 2,
    "木曜日": 3,
    "金曜日": 4,
    "土曜日": 5,
    "日曜日": 6,
}

# 1 枠の時間帯を拾う。Google Places は以下の 2 形式を返す（同じ locale でも混在する）:
#   - 長い日本語: "9時00分～17時00分"
#   - 短い HH:MM: "9:00～17:00" または "09:00～17:00"
# "～" / "〜" / "~" / "-" 全てに対応。
# 時間部分のキャプチャ: (open_h, open_m, close_h, close_m)
_SLOT_PATTERN = re.compile(
    r"(\d{1,2})(?:時(?:(\d{1,2})分)?|:(\d{2}))"
    r"\s*[～〜~–-]\s*"
    r"(\d{1,2})(?:時(?:(\d{1,2})分)?|:(\d{2}))"
)

_CLOSED_KEYWORDS = ("定休日", "休業", "休み")
_24H_KEYWORDS = ("24 時間", "24時間", "24時間営業", "24 時間営業")


@dataclass
class OpeningHoursParseResult:
    slots: list[OpeningHoursSlot] = field(default_factory=list)
    unknown_days: list[int] = field(default_factory=list)


def parse_weekday_descriptions(descriptions: list[str]) -> OpeningHoursParseResult:
    """Google の weekdayDescriptions を構造化する。

    - parse 成功: slots に OpeningHoursSlot を追加
    - 明示的定休日: slot を生成しない、unknown にもしない
    - parse 失敗 (非定型フォーマット): その曜日を unknown_days に登録
    - 曜日名が認識できない行: warning ログして無視
    """
    result = OpeningHoursParseResult()
    for line in descriptions:
        if not isinstance(line, str):
            continue
        day_index = _extract_day_index(line)
        if day_index is None:
            logger.warning(f"opening_hours: unrecognized weekday in %r", line)
            continue

        body = _extract_body(line)
        if body is None:
            # ": " が無くて body が取れない → 非定型、unknown に
            result.unknown_days.append(day_index)
            continue

        if _is_closed(body):
            continue
        if _is_24h(body):
            result.slots.append(
                OpeningHoursSlot(day_of_week=day_index, open_hhmm="00:00", close_hhmm="23:59")
            )
            continue

        matches = _SLOT_PATTERN.findall(body)
        if not matches:
            # 時間帯が 1 つも見つからない → unknown に
            result.unknown_days.append(day_index)
            continue

        # regex は (open_h, open_m_jp, open_m_colon, close_h, close_m_jp, close_m_colon) を返す。
        # 日本語長形式と HH:MM 形式を統一して (h, m) に整える。
        for open_h, open_m_jp, open_m_colon, close_h, close_m_jp, close_m_colon in matches:
            try:
                slot = OpeningHoursSlot(
                    day_of_week=day_index,
                    open_hhmm=_format_hhmm(open_h, open_m_jp or open_m_colon),
                    close_hhmm=_format_hhmm(close_h, close_m_jp or close_m_colon),
                )
                result.slots.append(slot)
            except Exception as e:
                # Pydantic の時刻範囲違反（24時超など）→ unknown にして続行
                logger.warning(
                    f"opening_hours: slot validation failed for %r: %s", line, e
                )
                result.unknown_days.append(day_index)
                break
    return result


def _extract_day_index(line: str) -> int | None:
    for name, idx in _JAPANESE_WEEKDAYS.items():
        if line.startswith(name):
            return idx
    return None


def _extract_body(line: str) -> str | None:
    """`"月曜日: 9時00分～17時00分"` から `"9時00分～17時00分"` を取り出す。"""
    if ":" in line:
        return line.split(":", 1)[1].strip()
    if "：" in line:  # 全角コロン
        return line.split("：", 1)[1].strip()
    return None


def _is_closed(body: str) -> bool:
    return any(kw in body for kw in _CLOSED_KEYWORDS)


def _is_24h(body: str) -> bool:
    return any(kw in body for kw in _24H_KEYWORDS)


def _format_hhmm(hour_str: str, minute_str: str | None) -> str:
    hour = int(hour_str)
    minute = int(minute_str) if minute_str else 0
    return f"{hour:02d}:{minute:02d}"
