import type { Participant } from "shared-types";

const PLAN_ID = "00000000-0000-0000-0000-000000000001";

export const mockParticipants: Participant[] = [
  {
    id: "p1",
    plan_id: PLAN_ID,
    display_name: "さとし",
    avatar_color: "#d97757",
    wishes_text: "温泉に入ってゆったりしたい。美味しいご飯も食べたい。",
    tags: ["温泉", "和食"],
    order_index: 0,
  },
  {
    id: "p2",
    plan_id: PLAN_ID,
    display_name: "あや",
    avatar_color: "#2c5f5d",
    wishes_text: "自然と景色を楽しみたい。写真映えするところも行きたい。",
    tags: ["自然", "写真", "観光"],
    order_index: 1,
  },
  {
    id: "p3",
    plan_id: PLAN_ID,
    display_name: "りょう",
    avatar_color: "#3a7d44",
    wishes_text: "アート系の美術館に興味あり。歩きすぎない程度に。",
    tags: ["アート", "ゆったり派"],
    order_index: 2,
  },
];
