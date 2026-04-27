"use client";

import { useMemo } from "react";
import Map, { Marker } from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import { MapPin } from "@phosphor-icons/react/dist/ssr";
import type { PlanItem } from "shared-types";

import { ErrorState } from "./ui/states/ErrorState";
import { EmptyState } from "./ui/states/EmptyState";

type Props = {
  items: PlanItem[];
};

/**
 * 地図ビュー。Mapbox GL を初期化し、lat/lng を持つ PlanItem をマーカー表示する。
 *
 * 経路ポリラインは Phase 1.8 本実装（別 PR）で追加。ここは骨組みなのでマーカーのみ。
 * デザイナーはマーカーデザインや style URL を調整してよい。
 */
export function MapView({ items }: Props) {
  const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

  const positioned = useMemo(
    () =>
      items.filter(
        (i): i is PlanItem & { location: { lat: number; lng: number } } =>
          // location 自体が undefined のケース（transit item 等）も除外
          i.location != null &&
          i.location.lat !== null &&
          i.location.lng !== null,
      ),
    [items],
  );

  const initialView = useMemo(() => {
    if (positioned.length === 0) {
      // 日本中心（おおよそ富士山）にフォールバック
      return { latitude: 35.3606, longitude: 138.7274, zoom: 8 };
    }
    // 最初のアイテムを中心に、複数ある場合は zoom を控えめに
    const center = positioned[0].location;
    return {
      latitude: center.lat,
      longitude: center.lng,
      zoom: positioned.length > 1 ? 11 : 13,
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
        mapboxAccessToken={token}
        initialViewState={initialView}
        style={{ width: "100%", height: "100%" }}
        mapStyle="mapbox://styles/mapbox/light-v11"
      >
        {positioned.map((item) => (
          <Marker
            key={item.id}
            latitude={item.location.lat}
            longitude={item.location.lng}
            anchor="bottom"
          >
            <MapPin
              size={28}
              weight="fill"
              className="text-[color:var(--color-primary)] drop-shadow-sm"
              aria-label={item.location.place_name ?? item.title}
            />
          </Marker>
        ))}
      </Map>
    </div>
  );
}
