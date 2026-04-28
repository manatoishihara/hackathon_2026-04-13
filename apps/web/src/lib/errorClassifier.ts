import { ApiError } from "@/lib/api";

export type ClassifiedError = { message: string; detail?: string };

export function classifyError(err: unknown): ClassifiedError {
  if (
    err instanceof TypeError &&
    (err.message.includes("fetch") ||
      err.message.includes("network") ||
      err.message.includes("Failed to fetch"))
  ) {
    return {
      message: "サーバーに接続できませんでした",
      detail: "インターネット接続またはサーバーの状態を確認してください。",
    };
  }
  if (err instanceof DOMException && err.name === "AbortError") {
    return {
      message: "接続がタイムアウトしました",
      detail:
        "サーバーの応答が遅い可能性があります。しばらくしてから再試行してください。",
    };
  }

  if (err instanceof ApiError) {
    if (err.status === 422) {
      return {
        message: "条件に合うプランを組み立てられませんでした",
        detail:
          "予算が低すぎる・期間が短すぎる・希望が多すぎる、などの可能性があります。予算を上げる、日数を増やす、希望を絞るなどしてもう一度お試しください。",
      };
    }
    if (err.status === 429) {
      return {
        message: "リクエストが集中しています（429）",
        detail: "少し時間をおいてから再試行してください。",
      };
    }
    if (err.status === 401) {
      return {
        message: "セッション認証エラー（401）",
        detail: "ページを再読み込みしてください。",
      };
    }
    if (err.status === 403) {
      return {
        message: "アクセス権限エラー（403）",
        detail: "APIキーの制限または権限設定の問題の可能性があります。",
      };
    }
    if (err.status === 404) {
      return {
        message: "リソースが見つかりません（404）",
        detail:
          "セッションの有効期限が切れた可能性があります。最初からやり直してください。",
      };
    }
    if (err.status === 502 || err.status === 503 || err.status === 504) {
      return {
        message: `APIサーバーが応答していません（${err.status}）`,
        detail:
          "Render のコールドスタート中の可能性があります。30秒ほど待ってから再試行してください。",
      };
    }
    if (err.status === 500) {
      return {
        message: "サーバー内部エラー（500）",
        detail: err.message || "予期しないエラーが発生しました。",
      };
    }
    return {
      message: `エラーが発生しました（${err.status}）`,
      detail: err.message,
    };
  }

  if (err instanceof Error) {
    return { message: err.message };
  }
  return { message: "プラン生成に失敗しました" };
}
