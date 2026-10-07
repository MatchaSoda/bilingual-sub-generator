import React, { useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TableContainer from '@mui/material/TableContainer';
import Link from '@mui/material/Link';
import Chip from '@mui/material/Chip';
import TextField from '@mui/material/TextField';
import InputAdornment from '@mui/material/InputAdornment';

import SearchIcon from '@mui/icons-material/Search';

import { UploadRecord } from '../../../src/api';
import { bilibiliVideoUrl, cardSx, filledFieldSx, formatClock, ORIGIN_LABELS, youtubeVideoUrl } from '../../../src/automation';

// 投稿记录（uploads.jsonl）：从这个版本开始的每一次投稿，自动搬运、Web 投稿、补投脚本都记
const UploadsTable = ({ uploads, loading }: { uploads: UploadRecord[]; loading: boolean }) => {
  const [query, setQuery] = useState('');
  const visible = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return uploads;
    return uploads.filter((u) =>
      [u.bili_title, u.title, u.original_title, u.bvid, u.video_id].some((v) => (v || '').toLowerCase().includes(keyword))
    );
  }, [uploads, query]);

  return (
    <Paper elevation={0} sx={{ ...cardSx, display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 900, flex: 1 }}>
          投稿记录 {uploads.length ? `（${uploads.length}）` : ''}
        </Typography>
        <TextField
          size="small"
          variant="filled"
          placeholder="搜标题 / BV 号 / 视频 ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          slotProps={{
            input: {
              disableUnderline: true,
              startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
            } as any,
          }}
          sx={{ ...filledFieldSx, minWidth: 260 }}
        />
      </Box>
      <Typography variant="caption" color="text.secondary">
        记录从这个功能上线开始；更早的稿件在 B 站创作中心看。审核状态以 B 站为准。
      </Typography>
      {loading && uploads.length === 0 ? (
        <Typography variant="body2" color="text.secondary">读取中…</Typography>
      ) : visible.length === 0 ? (
        <Typography variant="body2" color="text.secondary">{uploads.length ? '没有匹配的记录' : '还没有投稿记录'}</Typography>
      ) : (
        <TableContainer sx={{ maxHeight: 640 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>时间</TableCell>
                <TableCell>B 站标题</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>稿件</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>原视频</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>来源</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visible.map((u, i) => (
                <TableRow key={`${u.video_id}-${u.uploaded_at}-${i}`} hover>
                  <TableCell sx={{ whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: 12 }}>
                    {formatClock(u.uploaded_at)}
                  </TableCell>
                  <TableCell sx={{ wordBreak: 'break-word' }}>
                    {u.bili_title || u.title}
                    {u.original_title && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>{u.original_title}</Typography>
                    )}
                  </TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    {u.bvid ? (
                      <Link href={bilibiliVideoUrl(u.bvid)} target="_blank" rel="noreferrer">{u.bvid}</Link>
                    ) : '—'}
                  </TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    <Link href={u.url || youtubeVideoUrl(u.video_id)} target="_blank" rel="noreferrer" color="inherit">
                      {u.video_id}
                    </Link>
                  </TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    <Chip size="small" variant="outlined" label={ORIGIN_LABELS[u.origin || 'auto'] || u.origin} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Paper>
  );
};

export default UploadsTable;
