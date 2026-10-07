import React, { useMemo } from 'react';
import qrcode from 'qrcode-generator';

// 二维码一律白底黑块：深色主题下反色的码，B 站 App 经常扫不出来
const QrCode = ({ value, size = 220 }: { value: string; size?: number }) => {
  const { path, extent } = useMemo(() => {
    const qr = qrcode(0, 'M');
    qr.addData(value);
    qr.make();
    const count = qr.getModuleCount();
    const margin = 2;
    let d = '';
    for (let row = 0; row < count; row += 1) {
      for (let col = 0; col < count; col += 1) {
        if (qr.isDark(row, col)) d += `M${col + margin} ${row + margin}h1v1h-1z`;
      }
    }
    return { path: d, extent: count + margin * 2 };
  }, [value]);

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${extent} ${extent}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label="B 站扫码登录二维码"
    >
      <rect width={extent} height={extent} fill="#ffffff" />
      <path d={path} fill="#000000" />
    </svg>
  );
};

export default QrCode;
