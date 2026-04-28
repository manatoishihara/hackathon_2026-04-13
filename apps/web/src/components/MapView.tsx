"use client";

import { useEffect, useMemo, useState } from "react";
import Map, {
  Marker,
  Source,
  Layer,
  type MapRef,
} from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import {
  BedIcon as Bed,
  ForkKnifeIcon as ForkKnife,
  MapPinIcon as MapPin,
} from "@phosphor-icons/react/dist/ssr";
import type { ItemType, PlanItem } from "shared-types";

import { ErrorState } from "./ui/states/ErrorState";
import { EmptyState } from "./ui/states/EmptyState";

type Props = {
  items: PlanItem[];
};

type MarkerVisual = {
  Icon: typeof MapPin;
  bg: string;
  ariaLabel: string;
};

// PlanItem.tsx の THUMB_THEMES と配色を揃える（種別の認知を画面間で一貫）
const MARKER_VISUALS: Record<ItemType, MarkerVisual> = {
  activity: { Icon: MapPin, bg: "#8FA3C0", ariaLabel: "観光" },
  meal: { Icon: ForkKnife, bg: "#C4A988", ariaLabel: "食事" },
  lodging: { Icon: Bed, bg: "#7A8B5C", ariaLabel: "宿泊" },
  transit: { Icon: MapPin, bg: "#A0B2B8", ariaLabel: "移動" },
};

type PositionedItem = PlanItem & {
  location: PlanItem["location"] & { lat: number; lng: number };
};

export function MapView({ items }: Props) {
  const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
  // Map インスタンスを state で保持。callback ref で setMapInstance を渡すと、
  // Map が attach / detach されたタイミングで state が更新され、useEffect の
  // 依存に含めることで「ref attach 後に必ず fit する」が成立する。
  // useRef だと attach タイミングを effect が拾えない（dynamic import で
  // 最初の effect run 時には ref がまだ null のため）。
  const [mapInstance, setMapInstance] = useState<MapRef | null>(null);

  const positioned = useMemo<PositionedItem[]>(
    () =>
      items.filter(
        (i): i is PositionedItem =>
          i.location != null &&
          i.location.lat !== null &&
          i.location.lng !== null,
      ),
    [items],
  );

  const initialView = useMemo(() => {
    if (positioned.length === 0) {
      return { latitude: 35.3606, longitude: 138.7274, zoom: 8 };
    }
    const center = positioned[0].location;
    return {
      latitude: center.lat,
      longitude: center.lng,
      zoom: positioned.length > 1 ? 11 : 13,
    };
  }, [positioned]);

  // Day 切り替えで positioned が変わったら、その日のマーカー全部が画面に
  // 収まるよう中心と zoom を再計算する。initialViewState は初回マウント時しか
  // 効かないので、raw mapbox インスタンス経由で fitBounds / flyTo を直接呼ぶ。
  // mapInstance が依存に入っているので、ref attach 完了時にも 1 回必ず走る。
  // mapbox の flyTo / fitBounds は style 未ロード中に呼んでも内部で受け付けるので
  // isStyleLoaded ガードは不要。
  useEffect(() => {
    if (!mapInstance) return;
    const map = mapInstance.getMap();
    if (!map) return;
    if (positioned.length === 0) return;

    if (positioned.length === 1) {
      const { lat, lng } = positioned[0].location;
      map.flyTo({ center: [lng, lat], zoom: 13, duration: 600 });
      return;
    }
    const lats = positioned.map((i) => i.location.lat);
    const lngs = positioned.map((i) => i.location.lng);
    map.fitBounds(
      [
        [Math.min(...lngs), Math.min(...lats)],
        [Math.max(...lngs), Math.max(...lats)],
      ],
      { padding: 48, duration: 600, maxZoom: 14 },
    );
  }, [mapInstance, positioned]);

  // 訪問順を結ぶ LineString。マーカーが 1 個以下なら描画しない。
  const routeGeoJson = useMemo(() => {
    if (positioned.length < 2) return null;
    return {
      type: "Feature" as const,
      properties: {},
      geometry: {
        type: "LineString" as const,
        coordinates: positioned.map(
          (i) => [i.location.lng, i.location.lat] as [number, number],
        ),
      },
    };
  }, [positioned]);

  if (!token) {
    return (
      <ErrorState
        title="地図を表示できません"
        message="NEXT_PUBLIC_MAPBOX_TOKEN が設定されていません。.env.local を確認してください。"
      />
    );
  }

  if (positioned.length === 0) {
    return (
      <EmptyState
        icon={<MapPin size={32} weight="duotone" />}
        title="地図にプロットできる場所がまだありません"
        description="プランに座標付きのスポットが追加されると、ここに表示されます。"
      />
    );
  }

  return (
    <div className="h-full min-h-[200px] w-full overflow-hidden rounded-md border border-[color:var(--color-border)]">
      <Map
        ref={setMapInstance}
        mapboxAccessToken={token}
        initialViewState={initialView}
        style={{ width: "100%", height: "100%" }}
        mapStyle="mapbox://styles/mapbox/light-v11"
      >
        {routeGeoJson && (
          <Source id="plan-route" type="geojson" data={routeGeoJson}>
            <Layer
              id="plan-route-line"
              type="line"
              paint={{
                "line-color": "#042C53",
                "line-width": 2,
                "line-dasharray": [2, 1.5],
                "line-opacity": 0.7,
              }}
              layout={{
                "line-cap": "round",
                "line-join": "round",
              }}
            />
          </Source>
        )}
        {positioned.map((item, index) => {
          const visual = MARKER_VISUALS[item.item_type];
          const Icon = visual.Icon;
          const placeName = item.location.place_name ?? item.title;
          return (
            <Marker
              key={item.id}
              latitude={item.location.lat}
              longitude={item.location.lng}
              anchor="bottom"
            >
              <button
                type="button"
                className="relative flex h-9 w-9 cursor-pointer items-center justify-center rounded-full border-2 border-white shadow-md transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-primary)] focus-visible:ring-offset-2"
                style={{ backgroundColor: visual.bg }}
                aria-label={`${index + 1}. ${visual.ariaLabel}: ${placeName} へ移動`}
                onClick={() => {
                  // PlanItem.tsx の <article data-plan-item-id={item.id}> を起点に
                  // タイムライン側の対応行へスクロール。block:'center' で目立たせる。
                  const target = document.querySelector(
                    `[data-plan-item-id="${item.id}"]`,
                  );
                  target?.scrollIntoView({
                    behavior: "smooth",
                    block: "center",
                  });
                }}
              >
                <Icon size={18} weight="fill" className="text-white" />
                <span
                  className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full font-mono text-[11px] font-semibold tabular-nums text-white shadow-sm"
                  style={{ backgroundColor: "var(--color-primary)" }}
                >
                  {index + 1}
                </span>
              </button>
            </Marker>
          );
        })}
      </Map>
    </div>
  );
}
