import React from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Alert from '@mui/material/Alert';
import Tooltip from '@mui/material/Tooltip';

import ScanIcon from '@mui/icons-material/Radar';
import PauseIcon from '@mui/icons-material/PauseCircleOutline';
import PlayIcon from '@mui/icons-material/PlayCircleOutline';
import CircleIcon from '@mui/icons-material/FiberManualRecord';

import { AutomationStatus } from '../../../src/api';
import {
  cardSx, formatDuration, formatRelative, PHASE_LABELS, SKIP_REASON_LABELS, STAGE_LABELS,
} from '../../../src/automation';

interface StatusCardProps {
  status: AutomationStatus | null;
  busy: boolean;
  onScan: () => void;
  onTogglePause: () => void;
}

// 服务在不在、在干什么、下一轮什么时候、上一轮的结果
export const describeMover = (status: AutomationStatus | null) => {
  const mover = status?.mover;
  if (!status || !mover) return { label: '读取中', color: 'text.secondary', detail: '' };
  if (!mover.online) {
    return {
      label: '未运行',
      color: 'error.main',
      detail: mover.heartbeat_at ? `最后一次心跳 ${formatRelative(mover.heartbeat_at)}` : '从没收到过 mover 的心跳',
    };
  }
  const current = mover.current;
  if (mover.phase === 'processing' && current) {
    const who = current.kind === 'manual' ? 'Web 投稿' : '自动搬运';
    const stage = current.stage ? ` · ${STAGE_LABELS[current.stage] || current.stage}` : '';
    return { label: '处理中', color: 'primary.main', detail: `${who}：${current.title || current.video_id || ''}${stage}` };
  }
  if (mover.phase === 'scanning') {
    const what = current?.stage === 'description' ? `拉简介：${current.title || ''}` : `扫描 ${current?.channel || '频道'}`;
    return { label: '扫描中', color: 'primary.main', detail: what };
  }
  if (status.paused) {
    return { label: '已暂停', color: 'warning.main', detail: '不扫描频道；Web 提交的投稿照常处理' };
  }
  if (mover.phase === 'idle') {
    return {
      label: '运行中',
      color: 'success.main',
      detail: mover.next_scan_at ? `休眠中，下一轮扫描 ${formatRelative(mover.next_scan_at)}` : '休眠中',
    };
  }
  return { label: '运行中', color: 'success.main', detail: PHASE_LABELS[mover.phase || ''] || '' };
};

const Stat = ({ label, value, color }: { label: string; value: React.ReactNode; color?: string }) => (
  <Box sx={{ minWidth: 72 }}>
    <Typography sx={{ fontSize: 22, fontWeight: 900, color: color || 'white', lineHeight: 1.2 }}>{value}</Typography>
    <Typography variant="caption" color="text.secondary">{label}</Typography>
  </Box>
);

const StatusCard = ({ status, busy, onScan, onTogglePause }: StatusCardProps) => {
  const summary = describeMover(status);
  const online = !!status?.mover?.online;
  // 正在扫的时候再点也只会在这一轮结束后马上再扫一轮，没意义
  const scanning = status?.mover?.phase === 'scanning' || status?.mover?.phase === 'cycle';
  const last = status?.mover?.last_cycle;
  const stats = status?.stats_24h;
  const skipped = stats ? Object.values(stats.skipped || {}).reduce((a, b) => a + b, 0) : 0;
  const skipDetail = stats
    ? Object.entries(stats.skipped || {})
        .filter(([, n]) => n)
        .map(([reason, n]) => `${SKIP_REASON_LABELS[reason] || reason} ${n}`)
        .join('，')
    : '';

  return (
    <Paper elevation={0} sx={{ ...cardSx, display: 'flex', flexDirection: 'column', gap: 2.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <CircleIcon sx={{ color: summary.color, fontSize: 18 }} />
        <Box sx={{ flex: 1, minWidth: 200 }}>
          <Typography variant="h5" sx={{ fontWeight: 900, color: summary.color, lineHeight: 1.2 }}>
            {summary.label}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-all' }}>{summary.detail}</Typography>
        </Box>
        <Tooltip title={online ? '不等休眠结束，马上扫一轮频道（暂停时也会扫这一次）' : 'mover 没在运行'}>
          <span>
            <Button variant="contained" startIcon={<ScanIcon />} disabled={!online || busy || scanning} onClick={onScan}>
              {scanning ? '正在扫描' : '立即扫描'}
            </Button>
          </span>
        </Tooltip>
        <Button
          variant="outlined"
          color={status?.paused ? 'success' : 'warning'}
          startIcon={status?.paused ? <PlayIcon /> : <PauseIcon />}
          disabled={!status || busy || !status.config_exists}
          onClick={onTogglePause}
        >
          {status?.paused ? '恢复自动扫描' : '暂停自动扫描'}
        </Button>
      </Box>

      {status && !online && (
        <Alert severity="warning">
          自动搬运服务（mover）没在运行：频道不会被扫描，Web 提交的投稿会一直排队。
          {status.automation_enabled === false
            ? ' userdata/.env 里 ENABLE_AUTOMATION=0，改成 1 后在宿主机执行 ./docker-start.sh。'
            : ' Docker 部署在宿主机执行 ./docker-start.sh，裸机部署 sudo systemctl start bili-mover。'}
        </Alert>
      )}
      {status?.config_error && <Alert severity="error">{status.config_error}</Alert>}
      {status && !status.config_exists && !status.config_error && (
        <Alert severity="info">还没有 config.json：在「频道」页加一个频道并保存就会创建。</Alert>
      )}

      <Box sx={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        <Stat label="24 小时投稿" value={stats?.uploaded ?? '—'} color="success.main" />
        <Stat label="24 小时失败" value={stats?.failed ?? '—'} color={stats?.failed ? 'error.main' : undefined} />
        <Stat label="24 小时跳过" value={stats ? skipped : '—'} />
        <Stat label="投稿队列" value={status ? status.queue.queued + (status.queue.running ? 1 : 0) : '—'} />
        <Stat
          label="扫描间隔"
          value={status?.check_interval_seconds ? formatDuration(status.check_interval_seconds) : '—'}
        />
      </Box>
      {skipDetail && (
        <Typography variant="caption" color="text.secondary">跳过原因：{skipDetail}</Typography>
      )}
      {last && (
        <Typography variant="caption" color="text.secondary">
          上一轮 {formatRelative(last.finished_at)}{last.forced ? '（手动触发）' : ''}：{last.channels} 个频道，
          列出 {last.found} 个视频，新视频 {last.new} 个，命中 {last.matched}，投稿成功 {last.uploaded}
          {last.failed ? `，失败 ${last.failed}` : ''}，用时 {formatDuration(last.finished_at - last.started_at)}。
        </Typography>
      )}
    </Paper>
  );
};

export default StatusCard;
