"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "@phosphor-icons/react/dist/ssr";

import { Label } from "@/components/ui/label";
import {
  PlacesConfigError,
  loadPlacesLibrary,
} from "@/lib/places-autocomplete";

const MAX_ANCHORS = 3;

type Props = {
  /** 現在選択中の place_id 配列（最大 3 件、form schema と直結） */
  value: string[];
  /** 選択変更コールバック */
  onChange: (next: string[]) => void;
};

/**
 * Phase 2.1 出発モード切替「アンカー」UI（polish 版）。
 *
 * 必ず含めたい場所を **Google Maps `PlaceAutocompleteElement`**（Places API (New)
 * の web component, `<gmp-place-autocomplete>`）で検索 → 選択 → chip 追加。
 * chip には日本語名（`箱根神社` 等）を表示し、内部的に place_id を保持する。
 * form schema は `value: string[]`（place_id のみ）のまま、name lookup は本コンポーネント
 * 内部の `useState<Map<string, string>>` で管理（Codex Major 1 設計通り）。
 *
 * UX:
 * - 入力欄に「箱根神社」と打つと Google から候補ドロップダウンが出る
 * - 候補クリックで place_id 取得 + `await place.fetchFields({ fields: ["displayName"] })`
 *   で日本語名を取得 → chip 追加
 * - chip の × で削除
 * - 最大 3 件で element 自体を hidden にして上限を視覚的に伝える
 *
 * 前提:
 * - `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` が設定済（HTTP referrer に Vercel 本番と
 *   localhost を許可、Phase 1.10 で対応済）
 * - Google Cloud Project に「**Places API (New)**」が enable されていること。
 *   legacy `Places API` は不要（公式 docs: place-autocomplete-new）
 * - SDK ロード失敗時は inline で fallback メッセージ表示し、UI は壊れない
 *
 * 履歴:
 * - 2026-04-25 改訂: legacy `google.maps.places.Autocomplete` から
 *   `PlaceAutocompleteElement` (web component, Places API (New)) に migrate。
 *   理由: 本番プロジェクトで legacy API enable していなかったため smoke test で
 *   "legacy Places API not enabled" エラー。Element は New のみで動作する。
 */
export function AnchorPicker({ value, onChange }: Props) {
  // PlaceAutocompleteElement を mount するコンテナ。Element 自身を直接 ref で
  // 持つと initial render 時には null なので、コンテナ + 動的 appendChild の構成。
  const containerRef = useRef<HTMLDivElement>(null);
  const elementRef = useRef<google.maps.places.PlaceAutocompleteElement | null>(
    null,
  );
  const handlerRef = useRef<((ev: Event) => void) | null>(null);

  // place_id → 表示名（日本語）。SDK 経由で追加した時のみ埋まる。
  // form 外部から渡された value（過去セッション復元など）は name 不明 → place_id 表示にフォールバック。
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);

  // useEffect 内 closure に最新 value/onChange を渡すための ref
  // （依存配列 [] で SDK を 1 回 attach、value 変化のたび re-attach は重い）
  const valueRef = useRef(value);
  useEffect(() => {
    valueRef.current = value;
  }, [value]);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    const container = containerRef.current;

    (async () => {
      try {
        const places = await loadPlacesLibrary();
        if (cancelled || !container) return;

        // PlaceAutocompleteElement を生成して container にマウント。
        // includedRegionCodes で日本のみに絞る（旧 componentRestrictions の置換）。
        const element = new places.PlaceAutocompleteElement({
          includedRegionCodes: ["jp"],
          // requestedLanguage: ja は setOptions で指定していないため Google が
          // ブラウザロケールから推測する。日本語ロケールなら「箱根神社」表示で OK。
        });
        elementRef.current = element;

        // gmp-select event: 候補選択時に発火。
        // payload は `PlacePredictionSelectEvent`、`placePrediction.toPlace()` →
        // `fetchFields(["displayName"])` で日本語名取得（公式 docs パターン）。
        const handler = async (ev: Event) => {
          const selectEv = ev as google.maps.places.PlacePredictionSelectEvent;
          const prediction = selectEv.placePrediction;
          if (!prediction) return;
          const place = prediction.toPlace();
          try {
            await place.fetchFields({ fields: ["displayName"] });
          } catch (err) {
            // fetchFields 失敗時は id だけで chip 追加するフォールバック
            console.warn("AnchorPicker: fetchFields failed", err);
          }
          const id = place.id;
          if (!id) return;
          // displayName は string | null | undefined（@types/google.maps）。
          // 取得失敗時は id を表示名にフォールバック。
          const name = place.displayName ?? id;

          const current = valueRef.current;
          if (current.includes(id)) {
            // 重複: element の input を空にして次回入力に備える
            try {
              element.value = "";
            } catch {
              /* element.value setter が未定義な実装に備えて noop */
            }
            return;
          }
          if (current.length >= MAX_ANCHORS) {
            try {
              element.value = "";
            } catch {
              /* noop */
            }
            return;
          }
          setNames((m) => {
            const next = new Map(m);
            next.set(id, name);
            return next;
          });
          onChangeRef.current([...current, id]);
          try {
            element.value = "";
          } catch {
            /* noop */
          }
        };
        handlerRef.current = handler;
        element.addEventListener("gmp-select", handler);

        // accessibility: a11y label を element に付与（shadow DOM 内 input には
        // 直接届かないが、外側の host element の aria-label として読み上げソフトに
        // 補足情報を伝える）
        element.setAttribute("aria-label", "スポット検索");

        container.appendChild(element);
      } catch (e) {
        if (cancelled) return;
        if (e instanceof PlacesConfigError) {
          setError(e.message);
        } else {
          setError("Places API の読み込みに失敗しました。");
        }
      }
    })();

    return () => {
      cancelled = true;
      const element = elementRef.current;
      const handler = handlerRef.current;
      if (element && handler) {
        element.removeEventListener("gmp-select", handler);
      }
      if (element && element.parentNode) {
        element.parentNode.removeChild(element);
      }
      elementRef.current = null;
      handlerRef.current = null;
    };
    // 意図的に依存配列空: SDK は 1 回だけ attach する。最新 value/onChange は ref で参照。
  }, []);

  const handleRemove = (placeId: string) => {
    onChange(value.filter((id) => id !== placeId));
    setNames((m) => {
      const next = new Map(m);
      next.delete(placeId);
      return next;
    });
  };

  const isFull = value.length >= MAX_ANCHORS;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {value.map((placeId) => {
          const display = names.get(placeId) ?? placeId;
          return (
            <span
              key={placeId}
              className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-primary)] bg-[color:var(--color-primary)]/8 px-3 py-1 text-xs font-medium text-[color:var(--color-primary)]"
            >
              <span>{display}</span>
              <button
                type="button"
                aria-label={`${display} を削除`}
                onClick={() => handleRemove(placeId)}
                className="-mr-1 rounded-full p-0.5 hover:bg-[color:var(--color-primary)]/15"
              >
                <X size={12} weight="bold" />
              </button>
            </span>
          );
        })}
        {value.length === 0 ? (
          <p
            data-testid="anchor-empty-state"
            className="text-xs text-[color:var(--color-text-tertiary)]"
          >
            まだスポットが登録されていません。下の検索から 1〜3 件選んでください。
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="anchor_search" id="anchor_search_label">
          スポット検索
        </Label>
        <div
          id="anchor_search"
          ref={containerRef}
          aria-labelledby="anchor_search_label"
          aria-hidden={isFull ? "true" : undefined}
          data-testid="anchor-autocomplete-host"
          // PlaceAutocompleteElement は shadow DOM 内で Material 3 をデフォルト採用し、
          // OS の prefers-color-scheme=dark で暗い surface に切り替わる。CSS custom
          // properties を継承させて、他の <Input /> （bg-card）と背景・テキスト・
          // 枠線・focus 色を blue hour に揃える。
          style={
            {
              "--gmp-mat-color-surface": "var(--color-surface)",
              "--gmp-mat-color-on-surface": "var(--color-text-primary)",
              "--gmp-mat-color-on-surface-variant":
                "var(--color-text-tertiary)",
              "--gmp-mat-color-outline": "var(--color-border)",
              "--gmp-mat-color-outline-decorative": "var(--color-border)",
              "--gmp-mat-color-primary": "var(--color-primary)",
              "--gmp-mat-color-secondary-container":
                "color-mix(in oklab, var(--color-primary) 8%, var(--color-surface))",
              "--gmp-mat-color-on-secondary-container":
                "var(--color-text-primary)",
            } as React.CSSProperties
          }
          className={[
            // 外枠と背景は Tailwind で他 input と揃える（shadow DOM 内は上記 custom
            // property で継承）。focus-within で枠線を Deep Navy に。
            "rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)]",
            "transition-colors focus-within:border-[color:var(--color-primary)]",
            isFull ? "pointer-events-none opacity-50" : "",
          ].join(" ")}
        />
      </div>

      <p className="text-xs text-[color:var(--color-text-tertiary)]">
        最大 3 件。入力すると候補が出るので選択してください。
        {isFull ? "（上限到達）" : null}
      </p>

      {error ? (
        <p className="text-xs text-[color:var(--color-danger)]">{error}</p>
      ) : null}
    </div>
  );
}
