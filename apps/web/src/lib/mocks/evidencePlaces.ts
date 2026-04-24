import type { EvidencePlacesResponse } from "shared-types";

/**
 * モック /api/evidence/places レスポンス（箱根エリア、4 スポット）。
 * 1.5 のフォーム submit 時、USE_MOCKS=1 なら API を叩かずこれを返す。
 */
export const mockEvidencePlacesResponse: EvidencePlacesResponse = {
  evidence_pack_id: "11111111-1111-1111-1111-111111111111",
  places: [
    {
      place_id: "ChIJ_mock_hakone_open_air",
      name: "箱根彫刻の森美術館",
      lat: 35.2449,
      lng: 139.0523,
    },
    {
      place_id: "ChIJ_mock_tenseien",
      name: "天成園",
      lat: 35.2304,
      lng: 139.1083,
    },
    {
      place_id: "ChIJ_mock_hakone_jinja",
      name: "箱根神社",
      lat: 35.2044,
      lng: 139.0263,
    },
    {
      place_id: "ChIJ_mock_owakudani",
      name: "大涌谷",
      lat: 35.2451,
      lng: 139.0205,
    },
  ],
};
