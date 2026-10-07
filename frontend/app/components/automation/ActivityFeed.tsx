import React, { useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Link from '@mui/material/Link';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';

import HistoryIcon from '@mui/icons-material/History';

import { AutomationEvent } from '../../../src/api';
import {
  bilibiliVideoUrl, cardSx, formatBytes, formatClock, ORIGIN_LABELS, SKIP_REASON_LABELS, STAGE_LABELS,
  youtubeVideoUrl,
} from '../../../src/automation';

type Filter = 'important' | 'all';

const EventLine = ({ event }: { event: AutomationEvent }) => {
  const video = event.video_id ? (
    <Link href={youtubeVideoUrl(event.video_id)} target="_blank" rel="noreferrer" color="inherit" underline="hover">
      {event.title || event.video_id}
    </Link>
  ) : null;
  const origin = event.origin && event.origin !== 'auto' ? `（${ORIGIN_LABELS[event.origin] || event.origin}）` : '';

  switch (event.type) {
    case 'uploaded':
      return (
        <>
          <Box component="span" sx={{ color: 'success.main', fontWeight: 700 }}>投稿成功{origin}</Box> {video}
          {event.bvid && (
            <>
              {' '}·{' '}
              <Link href={bilibiliVideoUrl(event.bvid)} target="_blank" rel="noreferrer">{event.bvid}</Link>
            </>
          )}
        </>
      );
    case 'failed':
      return (
        <>
          <Box component="span" sx={{ color: 'error.main', fontWeight: 700 }}>
            失败{origin}（{STAGE_LABELS[event.stage] || event.stage}）
          </Box>{' '}
          {video}
          <Box component="span" sx={{ display: 'block', color: 'text.secondary', fontSize: 12, wordBreak: 'break-all' }}>
            {event.error}
          </Box>
        </>
      );
    case 'match':
      return (
        <>
          <Box component="span" sx={{ color: 'primary.main', fontWeight: 700 }}>命中</Box> {video}
        </>
      );
    case 'skip':
      return (
        <>
          <Box component="span" sx={{ color: event.reason === 'description_failed' ? 'warning.main' : 'text.secondary' }}>
            跳过 · {SKIP_REASON_LABELS[event.reason] || event.reason}
            {event.word ? `「${event.word}」` : ''}
          </Box>{' '}
          {video}
        </>
      );
    case 'cycle':
      return (
        <Box component="span" sx={{ color: 'text.secondary' }}>
          一轮扫描结束{event.forced ? '（手动触发）' : ''}：新视频 {event.new}，命中 {event.matched}，投稿 {event.uploaded}
          {event.failed ? `，失败 ${event.failed}` : ''}
        </Box>
      );
    case 'cleanup':
      return (
        <Box component="span" sx={{ color: 'text.secondary' }}>
          定期清理：删了 {event.removed} 个超过 {event.keep_days} 天的文件，释放 {formatBytes(event.freed || 0)}
        </Box>
      );
    default:
      return <Box component="span">{event.type}</Box>;
  }
};

// 最近的判定和结果。「重要」只看投稿、失败、命中；跳过的视频很多，默认不显示
const ActivityFeed = ({ events }: { events: AutomationEvent[] }) => {
  const [filter, setFilter] = useState<Filter>('important');
  const visible = useMemo(
    () => (filter === 'all' ? events : events.filter((e) => ['uploaded', 'failed', 'match'].includes(e.type))),
    [events, filter]
  );

  return (
    <Paper elevation={0} sx={{ ...cardSx, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <HistoryIcon color="secondary" />
        <Typography variant="subtitle1" sx={{ fontWeight: 900, flex: 1 }}>最近动态</Typography>
        <ToggleButtonGroup size="small" exclusive value={filter} onChange={(_, v) => v && setFilter(v)}>
          <ToggleButton value="important" sx={{ px: 1.5, py: 0.25 }}>投稿与失败</ToggleButton>
          <ToggleButton value="all" sx={{ px: 1.5, py: 0.25 }}>全部</ToggleButton>
        </ToggleButtonGroup>
      </Box>
      {visible.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {events.length === 0 ? '还没有记录。mover 每处理或跳过一个新视频都会记一条。' : '这段时间没有投稿或失败。'}
        </Typography>
      ) : (
        <Box sx={{ maxHeight: 420, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 0.75, pr: 1 }}>
          {visible.map((event, i) => (
            <Box key={`${event.ts}-${i}`} sx={{ display: 'flex', gap: 1.5, fontSize: 13, lineHeight: 1.6 }}>
              <Typography component="span" sx={{ fontSize: 12, color: 'text.secondary', fontFamily: 'monospace', flexShrink: 0 }}>
                {formatClock(event.ts)}
              </Typography>
              <Box sx={{ minWidth: 0, wordBreak: 'break-word' }}>
                <EventLine event={event} />
              </Box>
            </Box>
          ))}
        </Box>
      )}
    </Paper>
  );
};

export default ActivityFeed;
