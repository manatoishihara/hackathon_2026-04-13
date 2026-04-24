"use client";

import QRCode from "react-qr-code";

type Props = {
  value: string;
  size?: number;
};

/**
 * 共有 URL を QR コードで表示。印刷・スクショ前提なので背景白で固定、ブランドカラーは乗せない。
 */
export function ShareQRCode({ value, size = 180 }: Props) {
  return (
    <div className="inline-block rounded-md border border-[color:var(--color-border)] bg-white p-4">
      <QRCode value={value} size={size} level="M" />
    </div>
  );
}
