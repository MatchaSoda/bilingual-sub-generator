import React from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Autocomplete from '@mui/material/Autocomplete';
import TextField from '@mui/material/TextField';
import Grid from '@mui/material/Grid';
import Alert from '@mui/material/Alert';

import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/DeleteOutline';
import UpIcon from '@mui/icons-material/ArrowUpward';
import DownIcon from '@mui/icons-material/ArrowDownward';
import TvIcon from '@mui/icons-material/LiveTv';

import { ChannelConfig } from '../../../src/api';
import { cardSx, filledFieldSx } from '../../../src/automation';
import { NumberField, TextInput } from './fields';

interface ChannelEditorProps {
  channels: ChannelConfig[];
  defaults: ChannelConfig;
  errors: Record<string, string>;
  onChange: (channels: ChannelConfig[]) => void;
}

// 频道列表。过滤语义见 docs/RUNBOOK.md §4：关键词查标题 + 简介，排除词只查标题
const ChannelEditor = ({ channels, defaults, errors, onChange }: ChannelEditorProps) => {
  const update = (index: number, patch: Partial<ChannelConfig>) =>
    onChange(channels.map((ch, i) => (i === index ? { ...ch, ...patch } : ch)));
  const move = (index: number, delta: number) => {
    const next = [...channels];
    const [item] = next.splice(index, 1);
    next.splice(index + delta, 0, item);
    onChange(next);
  };
  const remove = (index: number) => {
    const name = channels[index].name || channels[index].url || `第 ${index + 1} 个频道`;
    if (!confirm(`删除频道「${name}」？保存之后才会生效。`)) return;
    onChange(channels.filter((_, i) => i !== index));
  };
  const add = () =>
    onChange([
      ...channels,
      { name: '', url: '', keyword: '', exclude: [], bili_tid: defaults?.bili_tid ?? 171, tags: defaults?.tags ?? '' },
    ]);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Alert severity="info" sx={{ bgcolor: 'rgba(59,130,246,0.08)' }}>
        每轮扫描每个频道最近的视频：<b>排除词</b>只看标题，标题含任一词就跳过；<b>关键词</b>标题没命中时会再去拉简介
        （每个约 10 秒，也是最容易触发 YouTube 风控的请求），标题或简介含关键词才处理，留空 = 全部处理。
        处理过、跳过的视频都会记进历史，不会再看第二遍。
      </Alert>

      {channels.map((channel, index) => {
        const err = (field: string) => errors[`channels[${index}].${field}`];
        return (
          <Paper key={index} elevation={0} sx={{ ...cardSx, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <TvIcon color="secondary" />
              <Typography variant="subtitle1" sx={{ fontWeight: 900, flex: 1 }}>
                {channel.name || channel.url || `新频道 ${index + 1}`}
              </Typography>
              <Tooltip title="上移">
                <span>
                  <IconButton size="small" disabled={index === 0} onClick={() => move(index, -1)}><UpIcon /></IconButton>
                </span>
              </Tooltip>
              <Tooltip title="下移">
                <span>
                  <IconButton size="small" disabled={index === channels.length - 1} onClick={() => move(index, 1)}>
                    <DownIcon />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title="删除这个频道">
                <IconButton size="small" color="error" onClick={() => remove(index)}><DeleteIcon /></IconButton>
              </Tooltip>
            </Box>
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, md: 4 }}>
                <TextInput label="名字（只给日志和页面看）" value={channel.name} error={err('name')}
                  onChange={(name) => update(index, { name })} />
              </Grid>
              <Grid size={{ xs: 12, md: 8 }}>
                <TextInput label="频道视频页地址" value={channel.url} error={err('url')}
                  placeholder="https://www.youtube.com/@频道名/videos"
                  onChange={(url) => update(index, { url })} />
              </Grid>
              <Grid size={{ xs: 12, md: 4 }}>
                <TextInput label="关键词" value={channel.keyword} error={err('keyword')}
                  helper="标题或简介包含才处理，留空 = 全部"
                  onChange={(keyword) => update(index, { keyword })} />
              </Grid>
              <Grid size={{ xs: 12, md: 8 }}>
                <Autocomplete
                  multiple
                  freeSolo
                  autoSelect
                  options={[]}
                  value={channel.exclude || []}
                  onChange={(_, value) =>
                    update(index, { exclude: Array.from(new Set(value.map((v) => String(v).trim()).filter(Boolean))) })
                  }
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      InputProps={{ ...params.InputProps, disableUnderline: true }}
                      variant="filled"
                      label="排除词（只查标题）"
                      error={!!err('exclude')}
                      helperText={err('exclude') || '输入一个词按回车添加'}
                      sx={filledFieldSx}
                    />
                  )}
                />
              </Grid>
              <Grid size={{ xs: 12, md: 4 }}>
                <NumberField label="B 站分区 tid" value={channel.bili_tid} error={err('bili_tid')}
                  helper="分区编号，208 = 知识 › 校园学习"
                  onChange={(bili_tid) => update(index, { bili_tid })} />
              </Grid>
              <Grid size={{ xs: 12, md: 8 }}>
                <TextInput label="投稿标签（逗号分隔）" value={channel.tags} error={err('tags')}
                  onChange={(tags) => update(index, { tags })} />
              </Grid>
            </Grid>
          </Paper>
        );
      })}

      <Box>
        <Button variant="outlined" startIcon={<AddIcon />} onClick={add}>添加频道</Button>
      </Box>
    </Box>
  );
};

export default ChannelEditor;
