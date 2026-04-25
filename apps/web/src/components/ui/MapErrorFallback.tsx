"use client";

import { Component, type ReactNode } from "react";
import { MapPin } from "@phosphor-icons/react/dist/ssr";

type Props = { children: ReactNode };
type State = { hasError: boolean };

/**
 * MapView の読み込み失敗（Mapbox トークン切れ / ネットワークエラー）を
 * タイムライン表示から隔離する Error Boundary。
 * MapView の失敗がページ全体をクラッシュさせないようにする。
 */
export class MapErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  override render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full items-center justify-center gap-2 rounded-lg bg-[color:var(--color-border)] text-sm text-[color:var(--color-text-tertiary)]">
          <MapPin size={16} />
          <span>地図を読み込めません</span>
        </div>
      );
    }
    return this.props.children;
  }
}
