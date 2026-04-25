# パフォーマンス最適化 実装計画

**対象**: Routeful（Flask + Next.js + Supabase）  
**目的**: DB/アクセス集中時の高速データ取得・弱 WiFi 環境下でのページ読み込み改善・画像遅延読み込み

---

## 優先度マトリクス

| 優先度 | 施策 | 効果 | 実装コスト |
|---|---|---|---|
| 🔴 高 | Flask インメモリキャッシュ（共有プラン） | DB ヒット削減 | 小 |
| 🔴 高 | HTTP Cache-Control ヘッダー | CDN/ブラウザキャッシュ活用 | 小 |
| 🔴 高 | MapView dynamic import（Mapbox GL 遅延） | 初期バンドル -300KB | 小 |
| 🟡 中 | React Query staleTime 最適化 | 不要 API 呼び出し削減 | 小 |
| 🟡 中 | Flask-Limiter（レート制限） | 公開エンドポイント保護 | 小 |
| 🟡 中 | Flask gzip 圧縮 | JSON レスポンスサイズ削減 | 小 |
| 🟢 低 | Next.js Skeleton ローディング統一 | 弱 WiFi 体感改善 | 中 |
| 🟢 低 | Service Worker（オフラインキャッシュ） | 弱 WiFi 時の閲覧継続 | 大 |

---

## 🔴 P1: Flask インメモリキャッシュ（共有プラン API）

### 問題
`GET /api/plans/shared/:token` は認証不要の公開エンドポイントで、
共有プランは `succeeded` 後に内容が変わらない。
アクセスが集中しても毎回 DB を叩いている。

### 実装ファイル
`apps/api/src/cache/plan_cache.py`（新規作成）

### 実装内容

```python
"""共有プランのインメモリ TTL キャッシュ。

succeeded プランは内容が変わらないため、TTL 60秒のキャッシュで
同一 token へのアクセスが集中しても DB クエリを1回に抑える。
"""
from __future__ import annotations

import threading
import time
from typing import Any

_SHARED_PLAN_TTL_SEC = 60
_cache: dict[str, tuple[Any, float]] = {}  # token -> (data, expires_at)
_lock = threading.Lock()


def get_cached_shared_plan(token: str) -> Any | None:
    with _lock:
        entry = _cache.get(token)
        if entry is None:
            return None
        data, expires_at = entry
        if time.monotonic() > expires_at:
            del _cache[token]
            return None
        return data


def set_cached_shared_plan(token: str, data: Any) -> None:
    with _lock:
        _cache[token] = (data, time.monotonic() + _SHARED_PLAN_TTL_SEC)


def invalidate_shared_plan(token: str) -> None:
    """share_token が再生成されたとき（将来の DELETE /share エンドポイント用）に呼ぶ。"""
    with _lock:
        _cache.pop(token, None)
```

### share_routes.py での使い方（DB-5 実装時に組み込む）

```python
from ..cache.plan_cache import get_cached_shared_plan, set_cached_shared_plan

@bp.get("/shared/<token>")
def get_shared_plan(token: str):
    # キャッシュヒット確認
    cached = get_cached_shared_plan(token)
    if cached is not None:
        return jsonify(cached), 200

    # DB から取得（get_shared_plan RPC）
    client = get_supabase_client()
    result = client.rpc("get_shared_plan", {"p_token": token}).execute()
    raw = result.data
    if raw is None:
        return jsonify({"error": "shared plan not found"}), 404

    # Pydantic で整形（session_id / share_token を除外）
    response = SharedPlanResponse(
        plan=SharedPlanSummary(**_build_plan(raw["plan"])),
        participants=[SharedParticipant(**p) for p in raw["participants"]],
        plan_items=[SharedPlanItem(**_build_item(i)) for i in raw["plan_items"]],
    )
    payload = response.model_dump(mode="json")

    # キャッシュに保存してから返す
    set_cached_shared_plan(token, payload)
    return jsonify(payload), 200
```

---

## 🔴 P1: HTTP Cache-Control ヘッダー

### 問題
API レスポンスにキャッシュヘッダーがなく、CDN（Render edge / Vercel）が
同一リソースを何度もオリジンに問い合わせている。

### 実装ファイル
`apps/api/src/routes/share_routes.py`（DB-5 実装時に追加）

### 実装内容

```python
from flask import make_response

@bp.get("/shared/<token>")
def get_shared_plan(token: str):
    # ... データ取得処理 ...
    
    resp = make_response(jsonify(payload), 200)
    # succeeded プランは内容が変わらないので 60s キャッシュ可
    # stale-while-revalidate=300: 300s まではキャッシュを返しつつバックグラウンドで更新
    resp.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    return resp
```

認証が必要なエンドポイント（`POST /api/plans/:id/share`）には：
```python
resp.headers["Cache-Control"] = "no-store"
```

---

## 🔴 P1: MapView の dynamic import（初期バンドル削減）

### 問題
`MapView.tsx` が `mapbox-gl`（~300KB）を静的 import しているため、
プラン閲覧画面の初期 JS バンドルが重い。
弱 WiFi では画面表示開始が遅れる。

### 実装ファイル
`apps/web/src/app/plan/[id]/page.tsx`

### 変更内容

```tsx
// 変更前
import { MapView } from "@/components/MapView";

// 変更後: dynamic import で Mapbox GL を遅延ロード
import dynamic from "next/dynamic";

const MapView = dynamic(
  () => import("@/components/MapView").then((m) => m.MapView),
  {
    ssr: false,   // Mapbox GL は SSR 不可
    loading: () => (
      <div className="h-full w-full animate-pulse rounded-lg bg-gray-100" />
    ),
  }
);
```

**効果**: 初期ページロード時に Mapbox GL の 300KB が含まれなくなる。
地図は画面外 or スクロール後にロードされるため、FCP（First Contentful Paint）が改善。

---

## 🟡 P2: React Query staleTime 最適化

### 問題
現状の `useQuery` に `staleTime` が設定されていないため、
画面を再フォーカスするたびに API を再呼び出ししている。

### 実装ファイル
`apps/web/src/app/plan/[id]/page.tsx`  
`apps/web/src/app/providers.tsx`（QueryClient 設定）

### providers.tsx の変更

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 60秒間はキャッシュをそのまま使う（同一画面の再マウント・再フォーカスで再取得しない）
      staleTime: 60 * 1000,
      // ガベージコレクション: 非アクティブになって5分後にキャッシュを破棄
      gcTime: 5 * 60 * 1000,
      // 弱 WiFi でリクエスト失敗した場合の自動リトライ: 2回まで
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
      // ネットワーク復帰時に自動再取得
      refetchOnReconnect: true,
      // ウィンドウフォーカス時の再取得は staleTime が切れていない限りスキップ
      refetchOnWindowFocus: false,
    },
  },
});
```

### 共有プランページ（認証不要）の staleTime はさらに長く

```tsx
// apps/web/src/app/plan/shared/[token]/page.tsx（DB-5 フロント実装時）
const sharedPlanQuery = useQuery({
  queryKey: ["shared-plan", token],
  queryFn: () => getSharedPlan(token),
  staleTime: 5 * 60 * 1000,  // 5分: 内容が変わらないので長くて良い
  gcTime: 30 * 60 * 1000,
});
```

---

## 🟡 P2: Flask-Limiter（レート制限）

### 問題
`GET /api/plans/shared/:token` は認証不要の公開エンドポイント。
悪意のある大量アクセスや scraping で DB/Flask が過負荷になるリスクがある。

### 実装ファイル
`apps/api/requirements.txt`（依存追加）  
`apps/api/src/app.py`（Limiter 初期化）  
`apps/api/src/routes/share_routes.py`（デコレータ）

### requirements.txt に追加
```
Flask-Limiter>=3.5,<4.0
```

### app.py

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],  # 全エンドポイント共通
    storage_uri="memory://",  # シングルワーカーなのでメモリで十分
)

def create_app() -> Flask:
    app = Flask(__name__)
    limiter.init_app(app)
    # ... 既存コード ...
```

### share_routes.py

```python
from ..app import limiter  # または Blueprint 単位で attach

@bp.get("/shared/<token>")
@limiter.limit("60 per minute")  # 公開エンドポイントは IP ごとに 60/分
def get_shared_plan(token: str):
    ...

@bp.post("/<plan_id>/share")
@limiter.limit("10 per minute")  # 認証済みだが token 生成は低頻度のはず
@require_session
def create_share_token(plan_id: str):
    ...
```

---

## 🟡 P2: Flask gzip 圧縮

### 問題
Flask はデフォルトでレスポンスを圧縮しない。
JSON レスポンス（特に plan_items が多い場合）は gzip で 60〜80% 削減できる。

### 実装ファイル
`apps/api/requirements.txt`  
`apps/api/src/app.py`

### requirements.txt に追加
```
Flask-Compress>=1.15,<2.0
```

### app.py

```python
from flask_compress import Compress

def create_app() -> Flask:
    app = Flask(__name__)
    
    # gzip 圧縮: 1KB 以上の JSON / HTML レスポンスに適用
    app.config["COMPRESS_ALGORITHM"] = "gzip"
    app.config["COMPRESS_MIN_SIZE"] = 1024  # 1KB 未満は圧縮しない
    Compress(app)
    
    # ... 既存コード ...
```

**注**: gunicorn の前段に nginx を置く場合は nginx 側で gzip する方が効率的。
Render Free プランはリバースプロキシが Render edge なので Flask-Compress で対応するのが現実的。

---

## 🟢 P3: Skeleton ローディング統一（弱 WiFi 体感改善）

### 問題
現状の `LoadingState` は汎用スピナーで、弱 WiFi でデータ待ちの間
ユーザーがレイアウトを予測できない。
Skeleton UI にすることで「何かが来る」感を与え体感速度が改善する。

### 実装ファイル
`apps/web/src/components/ui/states/SkeletonPlanItem.tsx`（新規）  
`apps/web/src/app/plan/[id]/page.tsx`

### SkeletonPlanItem.tsx（新規作成）

```tsx
export function SkeletonPlanItem() {
  return (
    <div className="flex gap-3 py-4 animate-pulse">
      <div className="w-12 h-12 rounded-full bg-gray-200 shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-4 bg-gray-200 rounded w-3/4" />
        <div className="h-3 bg-gray-100 rounded w-1/2" />
        <div className="h-3 bg-gray-100 rounded w-2/3" />
      </div>
    </div>
  );
}

export function SkeletonTimeline() {
  return (
    <div className="space-y-1">
      {Array.from({ length: 5 }).map((_, i) => (
        <SkeletonPlanItem key={i} />
      ))}
    </div>
  );
}
```

### plan/[id]/page.tsx での差し替え

```tsx
// 変更前
if (planQuery.isLoading) return <LoadingState />;

// 変更後: ローディング中もレイアウトを維持し Skeleton を表示
<div className="grid grid-cols-[1.35fr_1fr] gap-6">
  <div>
    {itemsQuery.isLoading ? <SkeletonTimeline /> : <PlanTimeline ... />}
  </div>
  <div>
    {/* MapView は dynamic import で独立ロード */}
    <MapView items={itemsQuery.data ?? []} />
  </div>
</div>
```

---

## 🟢 P3: Service Worker（オフライン・弱 WiFi 対応）

### 問題
WiFi が途切れると React Query のキャッシュは残っているが
ページリロードすると全データが消える。
閲覧済みの共有プランをオフラインでも見られると体験が大きく改善する。

### 実装ファイル
`apps/web/public/sw.js`（新規）  
`apps/web/src/app/layout.tsx`（SW 登録）

### sw.js（Cache First 戦略）

```js
const CACHE_NAME = "routeful-v1";
const STATIC_ASSETS = ["/", "/_next/static/**"];

// インストール時: 静的アセットをキャッシュ
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
});

// フェッチ: 共有プラン API は Network First + キャッシュフォールバック
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // 共有プラン API: ネットワーク優先、失敗時キャッシュから返す
  if (url.pathname.startsWith("/api/plans/shared/")) {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // 静的アセット: キャッシュ優先
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached ?? fetch(event.request))
    );
  }
});
```

### layout.tsx への SW 登録

```tsx
// apps/web/src/app/layout.tsx
"use client";
import { useEffect } from "react";

export function ServiceWorkerRegistrar() {
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(console.error);
    }
  }, []);
  return null;
}
```

---

## ② CDN（Cloudflare）— API レスポンスをエッジキャッシュ

### 問題
フロント（Vercel）は Vercel の global CDN で静的アセットを配信済み。
しかし API（Render）はオリジン直叩きで、`/api/plans/shared/:token` のような
キャッシュ可能なレスポンスもエッジにキャッシュされていない。

### 実装方法（設定のみ、コード変更なし）

**Cloudflare を Render の前段に置く手順:**
1. Cloudflare に Routeful のドメインを追加（無料プラン可）
2. DNS で API サブドメイン（例: `api.routeful.app`）を Render の URL に CNAME 設定、プロキシ ON（オレンジ雲）
3. Cloudflare > Rules > Cache Rules を追加:
   - URL パターン: `api.routeful.app/api/plans/shared/*`
   - Cache status: `Eligible for cache`
   - Edge TTL: `60 seconds`
4. `Cache-Control: public, max-age=60` が Flask から返されていれば Cloudflare が自動キャッシュ

**効果:**
- 同一 token への 2 回目以降のアクセスはオリジン（Render/Flask）に届かず Cloudflare エッジから返る
- Render の cold start ペナルティを共有プランアクセスで回避できる
- 無料プランで日本→Cloudflare は東京 PoP 経由（低レイテンシ）

**注意:**
- `POST /api/plans/:id/share` や認証付きエンドポイントは Cache Rule から除外する
- Render の `CORS_ALLOWED_ORIGINS` に Cloudflare 経由の本番ドメインを追加する

---

## ③⑦ SELECT * 廃止・クエリ最小化（実装済み: migration v2）

### 問題と対応
`get_shared_plan` RPC v1（`20260425_06`）が `to_jsonb(p.*)` で全カラムを取得していた。
`session_id` / `share_token` / `plan_id` など Flask 側で除外するカラムが
Supabase → Render 間のネットワークを流れていた。

### 対応（`supabase/migrations/20260425_07_shared_plan_rpc_v2.sql` で実装済み）
- `plans`: `jsonb_build_object(...)` で SharedPlanSummary に必要な 13 カラムのみ
- `participants`: 同様に 6 カラムのみ、`LIMIT 5`（ドメイン最大人数）
- `plan_items`: 同様に 20 カラムのみ、`LIMIT 100`（異常データ対策）

### EXPLAIN による確認方法（Supabase SQL Editor で実行）

```sql
-- 実際のクエリ実行計画を確認する
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT get_shared_plan('<実際の share_token>');

-- インデックスが使われているか確認
-- "Index Scan using idx_plans_share_token" が出ていれば OK
-- "Seq Scan on plans" が出ていたらインデックスが効いていない
```

---

## ⑧ プリレンダリング（Next.js ISR）— 共有プランページ

### 問題
共有プランページ `/plan/shared/[token]` (DB-5 フロント実装時に作成) を
`"use client"` で作ると、毎回 API を叩いてから描画する。
`succeeded` 状態のプランは内容が変わらないため、ISR で静的ページをキャッシュできる。

### 実装ファイル
`apps/web/src/app/plan/shared/[token]/page.tsx`（DB-5 フロント実装時に新規作成）

### 実装内容

```tsx
// Server Component（"use client" を付けない）
// Vercel が 60 秒ごとに再生成 → 初回以降は静的 HTML を返す
export const revalidate = 60;

type Props = { params: { token: string } };

export default async function SharedPlanPage({ params }: Props) {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}/api/plans/shared/${params.token}`,
    {
      next: { revalidate: 60 },   // Next.js fetch キャッシュ
    }
  );

  if (!res.ok) {
    return <SharedPlanNotFound />;
  }

  const data: SharedPlanResponse = await res.json();

  return <SharedPlanView plan={data.plan} participants={data.participants} planItems={data.plan_items} />;
}
```

**効果:**
- 1 回目のアクセスで Vercel がページを生成してエッジにキャッシュ
- 2 回目以降（60 秒以内）は Vercel エッジから静的 HTML を即返し
- Flask / Supabase に届かないためゼロ DB コスト
- QR コード経由で多人数が同時にアクセスしても Vercel エッジが捌く

---

## ⑩ 接続最適化（Keep-Alive / gunicorn チューニング）

### 実装済み（render.yaml）

`render.yaml` の startCommand に以下を追加済み:
```
--keep-alive 5 --worker-connections 100
```

| オプション | 意味 |
|---|---|
| `--keep-alive 5` | HTTP Keep-Alive タイムアウト 5 秒。クライアントが同一接続で複数リクエストを送れる |
| `--worker-connections 100` | sync worker では効かないが、将来 gthread worker に移行したときの上限設定 |

**HTTP/2 について:**
- Render edge（クライアント↔Render）は HTTP/2 対応済み（Render が自動でハンドリング）
- gunicorn↔Render 内部は HTTP/1.1 で問題なし（内部通信は高速ローカルネットワーク）
- Cloudflare を前段に置いた場合も Cloudflare が HTTP/2 を自動でクライアントに提供

---

## ⑭ フォールバック設計（落ちない設計）

### 実装ファイル
`apps/web/src/app/providers.tsx`  
`apps/web/src/app/plan/shared/[token]/page.tsx`（DB-5 フロント実装時）

### React Query: placeholderData でページ遷移を滑らかに

```tsx
// plan/[id]/page.tsx — 別プランに遷移した際に古いデータを表示し続ける
const itemsQuery = useQuery({
  queryKey: ["plan-items", planId],
  queryFn: () => getPlanItems(planId),
  placeholderData: (prev) => prev,  // 新データが来るまで前回データを維持
  staleTime: 60 * 1000,
});
```

### Flask: インメモリキャッシュが空でも graceful degradation

```python
# share_routes.py の get_shared_plan（DB-5 実装時）
@bp.get("/shared/<token>")
def get_shared_plan(token: str):
    # 1. キャッシュヒット確認
    cached = get_cached_shared_plan(token)
    if cached is not None:
        return jsonify(cached), 200

    # 2. DB（RPC）から取得
    try:
        result = client.rpc("get_shared_plan", {"p_token": token}).execute()
        raw = result.data
    except Exception as e:
        current_app.logger.error(f"get_shared_plan rpc failed: {e}")
        # 3. フォールバック: DB 障害でも 503 で理由を返す（500 にしない）
        return jsonify({"error": "service temporarily unavailable"}), 503

    if raw is None:
        return jsonify({"error": "shared plan not found"}), 404

    # 4. 整形 → キャッシュ保存 → 返却
    payload = _build_response(raw)
    set_cached_shared_plan(token, payload)
    return jsonify(payload), 200
```

### Next.js: Error Boundary で部分的エラーを隔離

```tsx
// apps/web/src/app/plan/[id]/page.tsx
import { ErrorBoundary } from "react-error-boundary";

// MapView の読み込み失敗（Mapbox トークン切れ等）がタイムライン表示を壊さないように分離
<ErrorBoundary fallback={<div className="text-sm text-gray-400">地図を読み込めません</div>}>
  <MapView items={items} />
</ErrorBoundary>
```

---

## 実装順序とチェックリスト（更新版）

### Step 0（実装済み ✅）
- [x] `supabase/migrations/20260425_05_index_optimization.sql` — 複合インデックス
- [x] `apps/api/src/supabase_client.py` — コネクションプール（シングルトン）
- [x] `supabase/migrations/20260425_06_shared_plan_rpc.sql` — 共有プラン一括取得 RPC v1
- [x] `supabase/migrations/20260425_07_shared_plan_rpc_v2.sql` — SELECT * 廃止 + LIMIT（⑦③）
- [x] `render.yaml` — `--keep-alive 5 --worker-connections 100` 追加（⑩）

### Step 1（DB-5 実装と同時に入れる、所要 1〜2 時間）
- [ ] `apps/api/src/cache/plan_cache.py` を新規作成（TTL キャッシュ）（①）
- [ ] `share_routes.py` の DB-5 エンドポイントにキャッシュ統合 + フォールバック設計（①⑭）
- [ ] Cache-Control ヘッダーを追加（⑨）
- [ ] MapView を dynamic import に変更（`apps/web/src/app/plan/[id]/page.tsx`）（⑥）
- [ ] React Query の `staleTime` / `gcTime` / `retry` / `placeholderData` をデフォルト設定（⑭）
- [ ] 共有プランページを Server Component + ISR で実装（⑧）

### Step 2（Step 1 完了後、所要 1〜2 時間）
- [ ] `Flask-Limiter` を requirements.txt に追加して app.py / share_routes.py に組み込む
- [ ] `Flask-Compress` を requirements.txt に追加して app.py に組み込む（⑤）
- [ ] SkeletonTimeline コンポーネントを作成して plan/[id]/page.tsx に適用（⑥）
- [ ] `react-error-boundary` を MapView に適用（⑭）

### Step 3（ハッカソン提出前に余裕があれば）
- [ ] Cloudflare を Render の前段に設定（ドメイン取得が前提）（②）
- [ ] Service Worker を実装（sw.js + SW 登録）
- [ ] `pnpm --filter web build` でバンドルサイズを確認（`next build` の出力で確認）
- [ ] EXPLAIN ANALYZE で get_shared_plan の実行計画を確認（⑦）

---

## 検証方法

```bash
# Flask レスポンス圧縮確認
curl -H "Accept-Encoding: gzip" -I https://routeful-api.onrender.com/api/plans/shared/<token>
# → Content-Encoding: gzip が付いていれば OK

# Cache-Control 確認
curl -I https://routeful-api.onrender.com/api/plans/shared/<token>
# → Cache-Control: public, max-age=60, stale-while-revalidate=300

# Next.js バンドルサイズ確認（MapView dynamic import 前後で比較）
cd apps/web && pnpm build
# First Load JS の plan/[id] が減っていれば OK（目安 -100〜300KB）

# レート制限確認（60回を超えたら 429 が返るか）
for i in $(seq 1 65); do curl -s -o /dev/null -w "%{http_code}\n" https://routeful-api.onrender.com/api/plans/shared/<token>; done
```

---

## このファイルを読み込んだ次セッションへの指示

このドキュメントを読んだら以下の順で実装せよ：

1. **Step 1 を全て実装してから** テスト（`pnpm --filter api test` + `pnpm --filter web test`）を通す
2. Step 2 は Step 1 がすべて PASS してから着手する
3. 各ステップ完了時に `tasks/todo.md` の該当チェックボックスを更新する
4. Flask-Limiter / Flask-Compress を追加したら `requirements.txt` のバージョン制約も必ず確認する
5. Service Worker（Step 3）は Next.js の `next/dist/client/sw.js` との干渉に注意。`/sw.js` は `apps/web/public/` 直下に置く

**触ってはいけないファイル**（handoff-db.md の担当範囲参照）:
- `apps/api/src/evidence/`
- `apps/api/src/llm/`
- `packages/shared-types/`
- `docs/data-model.md`
- `apps/api/src/schemas/__init__.py`
