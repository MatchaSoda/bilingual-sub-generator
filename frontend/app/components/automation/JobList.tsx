import React from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Chip from '@mui/material/Chip';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';

import SendIcon from '@mui/icons-material/Send';

import { PublishJob } from '../../../src/api';
import {
  bilibiliVideoUrl, cardSx, formatClock, formatRelative, JOB_STATUS_LABELS, STAGE_LABELS, youtubeVideoUrl,
} from '../../../src/automation';

const STATUS_COLORS: Record<string, 'default' | 'primary' | 'success' | 'error' | 'warning'> = {
  queued: 'warning',
  running: 'primary',
  done: 'success',
  failed: 'error',
  cancelled: 'default',
};

interface JobListProps {
  jobs: PublishJob[];
  onOpen: (job: PublishJob) => void;
  onCancel: (job: PublishJob) => void;
  onRetry: (job: PublishJob) => void;
  onNewJob: () => void;
}

// Web 提交的投稿任务（「制作任务」页选「生成并投稿」），mover 按提交顺序执行
const JobList = ({ jobs, onOpen, onCancel, onRetry, onNewJob }: JobListProps) => (
  <Paper elevation={0} sx={{ ...cardSx, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
      <SendIcon color="primary" />
      <Typography variant="subtitle1" sx={{ fontWeight: 900, flex: 1 }}>投稿队列</Typography>
      <Button size="small" onClick={onNewJob} sx={{ px: 1.5, py: 0.5 }}>投稿一个链接</Button>
    </Box>
    {jobs.length === 0 ? (
      <Typography variant="body2" color="text.secondary">
        还没有 Web 投稿任务。在「制作任务」页粘贴 YouTube 链接，选「生成并投稿 B 站」。
      </Typography>
    ) : (
      <Stack spacing={1}>
        {jobs.map((job) => {
          const bvid = job.result?.bvid;
          const when = job.status === 'queued' ? job.created_at : job.finished_at || job.started_at || job.created_at;
          return (
            <Box
              key={job.id}
              sx={{
                p: 1.5,
                borderRadius: 1.5,
                bgcolor: 'rgba(0,0,0,0.25)',
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                flexWrap: 'wrap',
              }}
            >
              <Chip
                size="small"
                color={STATUS_COLORS[job.status]}
                label={
                  job.status === 'queued' && job.queue_position
                    ? `排队第 ${job.queue_position}`
                    : job.status === 'running'
                      ? STAGE_LABELS[job.stage] || '进行中'
                      : JOB_STATUS_LABELS[job.status]
                }
                sx={{ fontWeight: 700, minWidth: 72 }}
              />
              <Box sx={{ flex: 1, minWidth: 180 }}>
                <Typography variant="body2" sx={{ fontWeight: 700, wordBreak: 'break-all' }}>
                  {job.result?.bili_title || job.title || job.options?.title || job.video_id}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {formatClock(when)}（{formatRelative(when)}）·{' '}
                  <Link href={youtubeVideoUrl(job.video_id)} target="_blank" rel="noreferrer" color="inherit">
                    {job.video_id}
                  </Link>
                  {bvid && (
                    <>
                      {' '}·{' '}
                      <Link href={bilibiliVideoUrl(bvid)} target="_blank" rel="noreferrer">{bvid}</Link>
                    </>
                  )}
                </Typography>
                {job.status === 'failed' && job.error && (
                  <Typography variant="caption" sx={{ display: 'block', color: 'error.light', wordBreak: 'break-all' }}>
                    {job.error}
                  </Typography>
                )}
              </Box>
              <Button size="small" onClick={() => onOpen(job)} sx={{ px: 1.5, py: 0.5 }}>日志</Button>
              {job.status === 'queued' && (
                <Button size="small" color="warning" onClick={() => onCancel(job)} sx={{ px: 1.5, py: 0.5 }}>取消</Button>
              )}
              {(job.status === 'failed' || job.status === 'cancelled') && (
                <Button size="small" onClick={() => onRetry(job)} sx={{ px: 1.5, py: 0.5 }}>重试</Button>
              )}
            </Box>
          );
        })}
      </Stack>
    )}
  </Paper>
);

export default JobList;
