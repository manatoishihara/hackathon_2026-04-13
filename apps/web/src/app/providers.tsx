"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // 60秒間はキャッシュをそのまま使う（再マウント・再フォーカスで再取得しない）
            staleTime: 60_000,
            // 非アクティブになって5分後にキャッシュを破棄
            gcTime: 5 * 60_000,
            // 弱 WiFi でリクエスト失敗した場合の自動リトライ（指数バックオフ）
            retry: 2,
            retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
            // ネットワーク復帰時に自動再取得
            refetchOnReconnect: true,
            // ウィンドウフォーカス時の再取得は staleTime が切れていない限りスキップ
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      {children}
      {process.env.NODE_ENV === "development" ? (
        <ReactQueryDevtools initialIsOpen={false} />
      ) : null}
    </QueryClientProvider>
  );
}
