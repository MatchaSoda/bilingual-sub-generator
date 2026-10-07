import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';

import ActivityIcon from '@mui/icons-material/Assessment';
import StatusIcon from '@mui/icons-material/FiberManualRecord';

import StageProgress from './StageProgress';
import { bilibiliVideoUrl, STAGE_LABELS, youtubeVideoUrl } from '../../src/automation';

interface TelemetryPanelProps {
  logs: string[];
  status: string;
  // /api/status 返回的整个任务（Web 任务或投稿任务），没有任务时是 null
  task?: any;
  onCancel?: () => void;
  onRetry?: () => void;
}

const ACTIVE = ['processing', 'queued', 'pending'];

// 投稿任务的那一行说明：排队到第几、mover 在忙什么、投稿结果
const PublishInfo = ({ task, onCancel, onRetry }: { task: any; onCancel?: () => void; onRetry?: () => void }) => {
  const job = task.job || {};
  const bvid = task.result?.bvid;
  const current = task.mover_current;
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
        投稿任务 {job.id} ·{' '}
        <Link href={youtubeVideoUrl(job.video_id)} target="_blank" rel="noreferrer" color="inherit">{job.video_id}</Link>
        {job.title ? ` · ${job.title}` : ''}
      </Typography>
      {task.status === 'queued' && (
        <Alert
          severity={task.mover_online ? 'info' : 'warning'}
          action={onCancel && <Button color="inherit" size="small" onClick={onCancel}>取消</Button>}
        >
          排在投稿队列第 {job.queue_position || 1} 位。
          {task.mover_online
            ? current && current.kind !== 'scan'
              ? ` 自动搬运正在处理「${current.title || current.video_id}」（${STAGE_LABELS[current.stage] || current.stage || ''}），完了就轮到它。`
              : ' 自动搬运几秒内就会开始处理。'
            : ' 自动搬运服务没在运行，启动之后才会开始处理。'}
        </Alert>
      )}
      {task.status === 'completed' && (
        <Alert severity="success">
          投稿成功：{task.result?.bili_title}
          {bvid ? (
            <>
              {' '}·{' '}
              <Link href={bilibiliVideoUrl(bvid)} target="_blank" rel="noreferrer">{bvid}</Link>（B 站审核通过后可见）
            </>
          ) : '（没拿到 BV 号，去 B 站创作中心看）'}
        </Alert>
      )}
      {task.status === 'failed' && (
        <Alert severity="error" action={onRetry && <Button color="inherit" size="small" onClick={onRetry}>重试</Button>}>
          {task.error || '失败了，看下面的日志'}
        </Alert>
      )}
      {task.status === 'cancelled' && (
        <Alert severity="info" action={onRetry && <Button color="inherit" size="small" onClick={onRetry}>重新提交</Button>}>
          已取消
        </Alert>
      )}
    </Stack>
  );
};

const TelemetryPanel = ({ logs, status, task, onCancel, onRetry }: TelemetryPanelProps) => {
  const active = ACTIVE.includes(status);
  const publish = task?.kind === 'publish';
  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 3, animate: 'fadeIn 0.5s ease-out' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 2 }}>
        <Typography
          variant="h4"
          sx={{
            fontWeight: 900,
            fontStyle: 'italic',
            textTransform: 'uppercase',
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            color: 'white'
          }}
        >
          <ActivityIcon sx={{ fontSize: 40, color: 'primary.main' }} />
          Telemetry
        </Typography>

        <Chip
          icon={active ? <CircularProgress size={16} color="inherit" /> : <StatusIcon />}
          label={`Status: ${status}`}
          variant="outlined"
          color={active ? 'primary' : status === 'completed' ? 'success' : status === 'failed' ? 'error' : 'default'}
          sx={{
            px: 2,
            py: 2.5,
            borderRadius: 2,
            fontWeight: 900,
            textTransform: 'uppercase',
            letterSpacing: 2,
            borderWidth: 2,
            bgcolor: active ? 'rgba(59, 130, 246, 0.1)' : 'rgba(0,0,0,0.5)',
            animation: active ? 'pulse 2s infinite' : 'none'
          }}
        />
      </Box>

      {task && status !== 'idle' && (
        <Paper
          elevation={0}
          sx={{
            p: 3,
            borderRadius: 2,
            bgcolor: 'rgba(255, 255, 255, 0.03)',
            border: '1px solid rgba(255, 255, 255, 0.05)',
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
          }}
        >
          {status !== 'queued' && status !== 'cancelled' && (
            <StageProgress stage={task.stage} status={status} withUpload={publish} />
          )}
          {publish && <PublishInfo task={task} onCancel={onCancel} onRetry={onRetry} />}
        </Paper>
      )}

      <Paper
        elevation={0}
        sx={{
          flex: 1,
          minHeight: 240,
          bgcolor: 'rgba(5, 7, 10, 0.6)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          borderRadius: 2,
          p: 4,
          fontFamily: 'monospace',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          position: 'relative',
          '&::-webkit-scrollbar': { width: 8 },
          '&::-webkit-scrollbar-thumb': { bgcolor: 'rgba(255,255,255,0.1)', borderRadius: 1 }
        }}
      >
        {logs.length === 0 ? (
          <Box sx={{
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: 0.05,
            userSelect: 'none'
          }}>
            <Typography variant="h1" sx={{ fontWeight: 900, fontStyle: 'italic', textTransform: 'uppercase', fontSize: '12vw' }}>
              Standby
            </Typography>
          </Box>
        ) : (
          <Stack spacing={1}>
            {logs.map((l, i) => (
              <Box
                key={i}
                sx={{
                  py: 1,
                  px: 3,
                  borderLeft: '2px solid rgba(59, 130, 246, 0.3)',
                  color: 'text.secondary',
                  fontWeight: 700,
                  fontSize: 13,
                  wordBreak: 'break-all',
                  '&:hover': { color: 'white', bgcolor: 'rgba(255,255,255,0.02)' }
                }}
              >
                {l}
              </Box>
            ))}
          </Stack>
        )}
      </Paper>
    </Box>
  );
};

export default TelemetryPanel;
