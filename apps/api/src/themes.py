"""Phase 2.1 出発モード切替: theme 定義の単一情報源（Codex Minor 5 対応）。

旧設計では builder.py の `_THEME_KEYWORDS`（pack 検索 keyword 拡張）、prompt.py の
`_THEME_LABEL_JP`（user prompt の日本語表示）、schemas の `ThemeKey`（Literal 型）が
3 箇所に分散していて、追加/改名時にずれて実害化するリスクがあった。
本モジュールに集約し、各 caller は registry を参照する。

注意: `ThemeKey` Literal 型は Python の typing 制約上、動的に生成できないため
THEME_REGISTRY のキー集合と「人手で同期」する必要がある。`THEME_KEYS_TUPLE` と
`_assert_registry_matches_literal()` で起動時に静的検証している。
"""

from __future__ import annotations

from typing import Literal, get_args


ThemeKey = Literal["onsen", "art", "gourmet", "nature", "history", "experience"]


# 各 theme の (日本語ラベル, 検索 keyword 配列)。pack 構築では region と組み合わせて
# search_by_text のクエリにする（例: "箱根 温泉"）。日本語ラベルは LLM user prompt の
# mode_context_md に表示される。
THEME_REGISTRY: dict[str, dict[str, object]] = {
    "onsen": {
        "label": "温泉",
        "keywords": ["温泉", "露天風呂", "旅館"],
    },
    "art": {
        "label": "アート",
        "keywords": ["美術館", "ギャラリー", "アート"],
    },
    "gourmet": {
        "label": "グルメ",
        "keywords": ["グルメ", "名物料理", "レストラン"],
    },
    "nature": {
        "label": "自然",
        "keywords": ["自然", "公園", "湖"],
    },
    "history": {
        "label": "歴史",
        "keywords": ["神社", "寺", "歴史"],
    },
    "experience": {
        "label": "体験",
        "keywords": ["体験", "工房", "アクティビティ"],
    },
}


def get_label(theme: str) -> str | None:
    """theme key から日本語ラベルを取得（不明 key は None）。"""
    entry = THEME_REGISTRY.get(theme)
    if not entry:
        return None
    label = entry.get("label")
    return label if isinstance(label, str) else None


def get_keywords(theme: str) -> list[str]:
    """theme key から検索 keyword 配列を取得（不明 key は []）。"""
    entry = THEME_REGISTRY.get(theme)
    if not entry:
        return []
    keywords = entry.get("keywords")
    return list(keywords) if isinstance(keywords, list) else []


def _assert_registry_matches_literal() -> None:
    """import 時に ThemeKey Literal と THEME_REGISTRY のキー集合が一致するか確認。
    どちらかを更新してもう一方を更新し忘れると起動時に AssertionError で気付ける。"""
    literal_keys = set(get_args(ThemeKey))
    registry_keys = set(THEME_REGISTRY.keys())
    if literal_keys != registry_keys:
        raise AssertionError(
            f"ThemeKey Literal と THEME_REGISTRY が drift: "
            f"literal={literal_keys}, registry={registry_keys}"
        )


_assert_registry_matches_literal()
