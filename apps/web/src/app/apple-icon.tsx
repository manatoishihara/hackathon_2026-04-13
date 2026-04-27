import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: 180,
          height: 180,
          background: "#042C53",
          borderRadius: 40,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg width="120" height="120" viewBox="0 0 32 32" fill="none">
          <circle cx="8" cy="24" r="2.5" fill="#F0997B" />
          <circle cx="24" cy="8" r="2.5" fill="#F0997B" />
          <path
            d="M8 24 Q8 8 24 8"
            stroke="#F0997B"
            strokeWidth="2.5"
            strokeLinecap="round"
            fill="none"
          />
          <circle cx="16" cy="16" r="2" fill="#F5EFE6" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
