import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GeneratePlanRequest, PlanGenerationPayload } from "shared-types";

// getSupabaseAccessToken をモック（fetch の Authorization ヘッダ検証用）
vi.mock("./supabase", () => ({
  getSupabaseAccessToken: vi.fn(async () => "mock-jwt-token"),
  getSupabaseClient: vi.fn(),
}));

// NEXT_PUBLIC_USE_MOCKS が "1" でない環境で fetch 経路を検証する
vi.stubEnv("NEXT_PUBLIC_USE_MOCKS", "");
vi.stubEnv("NEXT_PUBLIC_API_URL", "http://test.local");

const { ApiError, postEvidencePlaces, postPlanGenerate } = await import("./api");

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("postEvidencePlaces", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("正常系: Authorization ヘッダ付きで POST する", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ evidence_pack_id: "pack-1", places: [] }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const req: GeneratePlanRequest = {
      title: "箱根",
      region: "箱根",
      start_date: "2026-06-01",
      end_date: "2026-06-02",
      departure_point: "新宿駅",
      budget_per_person_jpy: 30000,
      budget_breakdown: { lodging: 40, meal: 30, activity: 20, transit: 10 },
      start_mode: "auto",
      mode_payload: null,
      participants: [],
    };

    const res = await postEvidencePlaces(req);
    expect(res.evidence_pack_id).toBe("pack-1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0]!;
    const url = call[0];
    const init = call[1] as RequestInit;
    expect(url).toBe("http://test.local/api/evidence/places");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      Authorization: "Bearer mock-jwt-token",
    });
    expect(JSON.parse(init.body as string)).toEqual(req);
  });

  it("異常系: 400 レスポンスで ApiError が throw される", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => jsonResponse({ error: "validation failed" }, 400)),
    );
    await expect(
      postEvidencePlaces({
        title: "x",
        region: "x",
        start_date: "2026-06-01",
        end_date: "2026-06-02",
        departure_point: "x",
        budget_per_person_jpy: 10000,
        budget_breakdown: { lodging: 40, meal: 30, activity: 20, transit: 10 },
        start_mode: "auto",
        mode_payload: null,
        participants: [],
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("postPlanGenerate", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("正常系: plan_id + evidence_pack_id + transit_matrix を送る", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse({ plan_id: null }));
    vi.stubGlobal("fetch", fetchMock);

    const payload: PlanGenerationPayload = {
      plan_id: "00000000-0000-0000-0000-000000000001",
      evidence_pack_id: "11111111-1111-1111-1111-111111111111",
      transit_matrix: [],
    };
    await postPlanGenerate(payload);

    const call = fetchMock.mock.calls[0]!;
    const url = call[0];
    const init = call[1] as RequestInit;
    expect(url).toBe("http://test.local/api/plans/generate");
    expect(JSON.parse(init.body as string)).toEqual(payload);
  });
});
