import React, { useEffect, useRef } from 'react';
import Box from '@mui/material/Box';

// 日志行的颜色：报错红、警告黄、成功绿，其余灰
const lineColor = (line: string) => {
  if (/❌|Traceback|Error|失败/.test(line)) return 'error.light';
  if (/⚠️|跳过 \(拉取描述失败|Warning/.test(line)) return 'warning.light';
  if (/✅|🎉|投稿成功/.test(line)) return 'success.light';
  if (/\[CLI\]/.test(line)) return 'text.secondary';
  return 'grey.300';
};

interface LogViewerProps {
  lines: string[];
  height?: number | string;
  emptyText?: string;
}

// 等宽日志框。停在底部时有新行就跟着滚；往上翻的时候不打扰
const LogViewer = ({ lines, height = 560, emptyText = '还没有日志' }: LogViewerProps) => {
  const boxRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  useEffect(() => {
    const box = boxRef.current;
    if (box && stickRef.current) box.scrollTop = box.scrollHeight;
  }, [lines]);

  return (
    <Box
      ref={boxRef}
      onScroll={(e) => {
        const box = e.currentTarget;
        stickRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
      }}
      sx={{
        height,
        overflowY: 'auto',
        bgcolor: 'rgba(5, 7, 10, 0.6)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: 2,
        p: 2,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: 12,
        lineHeight: 1.6,
        '&::-webkit-scrollbar': { width: 8 },
        '&::-webkit-scrollbar-thumb': { bgcolor: 'rgba(255,255,255,0.1)', borderRadius: 1 },
      }}
    >
      {lines.length === 0 ? (
        <Box sx={{ color: 'text.secondary' }}>{emptyText}</Box>
      ) : (
        lines.map((line, i) => (
          <Box key={i} sx={{ color: lineColor(line), whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {line}
          </Box>
        ))
      )}
    </Box>
  );
};

export default LogViewer;
