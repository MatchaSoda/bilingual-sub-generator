import React, { useEffect, useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import MenuItem from '@mui/material/MenuItem';
import Grid from '@mui/material/Grid';
import Alert from '@mui/material/Alert';
import Link from '@mui/material/Link';

import ZapIcon from '@mui/icons-material/Bolt';
import SettingsIcon from '@mui/icons-material/Settings';
import MovieIcon from '@mui/icons-material/Movie';
import SendIcon from '@mui/icons-material/Send';

import { AccountStatus, automationApi, AutomationConfigResponse, AutomationStatus, PublishRequest } from '../../src/api';
import { filledFieldSx, pickStyle, sameStyle, sameStyleValue, STYLE_KEYS } from '../../src/automation';
import { describeMover } from './automation/StatusCard';

export type TaskMode = 'generate' | 'publish';

interface TaskPanelProps {
  form: any;
  setForm: (form: any) => void;
  startTask: () => void;
  startPublish: (request: PublishRequest) => void;
  status: string;
  onNavigate: (tab: string) => void;
  mode: TaskMode;
  setMode: (mode: TaskMode) => void;
  automationStatus: AutomationStatus | null;
}

// 和后端 utils/automation_store.parse_youtube_url 同样的判断：投稿只收单个 YouTube 视频
const YOUTUBE_VIDEO = /^(https?:\/\/)?((www|m|music)\.)?(youtube\.com\/(watch\?(.*&)?v=|shorts\/|live\/|embed\/)|youtu\.be\/)[A-Za-z0-9_-]{11}(?![A-Za-z0-9_-])/;

const chipSx = { fontWeight: 900, textTransform: 'uppercase', fontSize: 10 };
const modelChipSx = { ...chipSx, borderColor: 'rgba(20, 184, 166, 0.3)', color: 'secondary.light' };
const shortModel = (model?: string) => (model || '').replace('gemini-', 'G-');

interface ProcessingSummary {
  whisper: string;
  translator: string;
  correction: string | null;   // 原文纠错用的模型；null = 没开
  furigana: boolean;
  customStyle: boolean | null; // null = 还不知道样式缺省值
}

// 两种模式显示同一组标签，只是参数来源不同：仅生成用「系统设置」「视觉实验室」，生成并投稿用「自动搬运 › 处理与投稿」
const ProcessingChips = ({ summary, onSettings }: { summary: ProcessingSummary; onSettings: () => void }) => (
  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" justifyContent="center" alignItems="center">
    <Chip variant="outlined" size="small" label={`ASR: ${summary.whisper}`}
      sx={{ ...chipSx, borderColor: 'rgba(59, 130, 246, 0.3)', color: 'primary.light' }} />
    <Chip variant="outlined" size="small" label={`Translator: ${shortModel(summary.translator)}`} sx={modelChipSx} />
    {summary.correction && (
      <Chip variant="outlined" size="small" label={`原文纠错: ${shortModel(summary.correction)}`} sx={modelChipSx} />
    )}
    {summary.furigana && <Chip variant="outlined" size="small" label="振假名" sx={chipSx} />}
    {summary.customStyle !== null && (
      <Chip variant="outlined" size="small" label={summary.customStyle ? '自定义样式' : '默认样式'} sx={chipSx} />
    )}
    <Button size="small" startIcon={<SettingsIcon sx={{ fontSize: 14 }} />} onClick={onSettings}
      sx={{ color: 'text.secondary', fontSize: 10, fontWeight: 900, '&:hover': { color: 'white', bgcolor: 'transparent' } }}>
      修改设置
    </Button>
  </Stack>
);

const TaskPanel = ({
  form, setForm, startTask, startPublish, status, onNavigate, mode, setMode, automationStatus,
}: TaskPanelProps) => {
  const [meta, setMeta] = useState<AutomationConfigResponse | null>(null);
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [channel, setChannel] = useState<number>(0);
  const [tid, setTid] = useState<string>('');
  const [tags, setTags] = useState('');
  const [title, setTitle] = useState('');

  const publish = mode === 'publish';
  const channels = meta?.effective.channels || [];

  // 切模式时拿一次处理预设（两种模式的标签都要用：投稿参数、样式缺省值）；投稿模式再拿账号状态
  useEffect(() => {
    automationApi.getConfig().then((res) => setMeta(res.data)).catch(() => setMeta(null));
    if (publish) automationApi.account(true).then((res) => setAccount(res.data)).catch(() => setAccount(null));
  }, [publish]);

  // 选哪个频道，分区和标签就先填那个频道的，可以再改
  useEffect(() => {
    const ch = channels[channel] || meta?.channel_defaults;
    if (ch) {
      setTid(String(ch.bili_tid ?? ''));
      setTags(ch.tags ?? '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel, meta]);

  const url = (form.url || '').trim();
  const urlInvalid = publish && url !== '' && !YOUTUBE_VIDEO.test(url);
  const processing = meta?.effective.processing;
  const summary: ProcessingSummary | null = publish
    ? processing ? {
        whisper: processing.whisper_model,
        translator: processing.gemini_model,
        correction: processing.fix_source_text ? processing.correction_model : null,
        furigana: processing.enable_furigana,
        customStyle: STYLE_KEYS.some((key) => processing.style?.[key] !== undefined
          && !sameStyleValue(key, processing.style[key], meta?.style_defaults[key])),
      } : null
    : {
        whisper: form.model,
        translator: form.translation_model,
        correction: form.fix_source ? form.correction_model || 'gemini-3.5-flash' : null,
        furigana: !!form.enable_furigana,
        customStyle: meta ? !sameStyle(pickStyle(form), meta.style_defaults) : null,
      };
  const mover = describeMover(automationStatus);
  const busy = status === 'processing' || status === 'queued' || status === 'pending';

  const submit = () => {
    if (!publish) {
      startTask();
      return;
    }
    const profile = channels[channel];
    const request: PublishRequest = { url, channel: channels.length ? channel : null };
    // 和频道默认值一样就不传，让 mover 用频道配置（之后改频道配置也跟着变）
    if (tid && Number(tid) !== profile?.bili_tid) request.tid = Number(tid);
    if (tags.trim() && tags.trim() !== (profile?.tags || '')) request.tags = tags.trim();
    if (title.trim()) request.title = title.trim();
    startPublish(request);
  };

  const accountWarning = useMemo(() => {
    if (!publish || !account) return null;
    if (!account.logged_in) return '还没有登录 B 站，投稿会失败：先去「自动搬运」页扫码登录';
    if (account.valid === false) return 'B 站登录已失效，投稿会失败：去「自动搬运」页重新扫码登录';
    return null;
  }, [publish, account]);

  return (
    <Box
      sx={{
        minHeight: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 5,
        py: 4,
      }}
    >
      <Box sx={{ textAlign: 'center' }}>
        <Typography
          variant="h2"
          sx={{
            fontWeight: 900,
            fontStyle: 'italic',
            textTransform: 'uppercase',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 2,
            mb: 1,
            color: 'white',
            textShadow: '0 10px 30px rgba(0,0,0,0.5)'
          }}
        >
          <ZapIcon sx={{ fontSize: 60, color: 'primary.main' }} />
          Initiate
        </Typography>
        <Typography
          variant="overline"
          sx={{
            fontSize: 14,
            letterSpacing: 4,
            color: 'text.secondary',
            fontWeight: 700
          }}
        >
          {publish ? '一个链接，从字幕到 B 站稿件。' : '大师级 1:1 物理渲染实验室。'}
        </Typography>
      </Box>

      <Paper
        elevation={0}
        sx={{
          width: '100%',
          maxWidth: 800,
          p: 5,
          borderRadius: 2,
          bgcolor: 'rgba(255, 255, 255, 0.03)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          backdropFilter: 'blur(20px)',
          display: 'flex',
          flexDirection: 'column',
          gap: 3
        }}
      >
        <ToggleButtonGroup
          exclusive
          fullWidth
          value={mode}
          onChange={(_, value) => value && setMode(value)}
          sx={{ '& .MuiToggleButton-root': { py: 1.25, fontWeight: 900, gap: 1 } }}
        >
          <ToggleButton value="generate"><MovieIcon fontSize="small" /> 仅生成字幕视频</ToggleButton>
          <ToggleButton value="publish"><SendIcon fontSize="small" /> 生成并投稿 B 站</ToggleButton>
        </ToggleButtonGroup>

        <TextField
          fullWidth
          variant="outlined"
          placeholder={publish ? 'PASTE YOUTUBE VIDEO LINK' : 'PASTE YOUTUBE / BILIBILI LINK'}
          value={form.url}
          onChange={(e) => setForm({...form, url: e.target.value})}
          error={urlInvalid}
          helperText={urlInvalid ? '投稿只支持单个 YouTube 视频链接（watch?v=、youtu.be、shorts）' : ' '}
          sx={{
            '& .MuiOutlinedInput-root': {
              borderRadius: 1,
              fontSize: '1.2rem',
              fontWeight: 900,
              letterSpacing: 1.5,
              backgroundColor: 'rgba(0,0,0,0.3)',
              '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' },
              '&:hover fieldset': { borderColor: 'primary.main' },
              '&.Mui-focused fieldset': { borderColor: 'primary.main' },
            },
            '& input': { textAlign: 'center' },
            '& .MuiFormHelperText-root': { textAlign: 'center' },
          }}
        />

        {summary && <ProcessingChips summary={summary} onSettings={() => onNavigate(publish ? 'automation' : 'settings')} />}

        {publish && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Grid container spacing={2}>
              {channels.length > 1 && (
                <Grid size={12}>
                  <TextField select fullWidth variant="filled" label="按哪个频道的设置投稿" value={channel}
                    onChange={(e) => setChannel(Number(e.target.value))}
                    slotProps={{ input: { disableUnderline: true } as any }} sx={filledFieldSx}>
                    {channels.map((ch, i) => (
                      <MenuItem key={i} value={i}>{ch.name || ch.url}（分区 {ch.bili_tid}）</MenuItem>
                    ))}
                  </TextField>
                </Grid>
              )}
              <Grid size={{ xs: 12, sm: 4 }}>
                <TextField fullWidth variant="filled" label="B 站分区 tid" value={tid} type="number"
                  onChange={(e) => setTid(e.target.value)}
                  slotProps={{ input: { disableUnderline: true } }} sx={filledFieldSx} />
              </Grid>
              <Grid size={{ xs: 12, sm: 8 }}>
                <TextField fullWidth variant="filled" label="标签（逗号分隔）" value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  slotProps={{ input: { disableUnderline: true } }} sx={filledFieldSx} />
              </Grid>
              <Grid size={12}>
                <TextField fullWidth variant="filled" label="B 站标题（可选）" value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={(meta?.effective.upload.title_template || '【双语字幕】{title}').replace('{title}', '翻译后的标题')}
                  helperText={`留空 = 按标题模板用自动翻译的标题；最多 80 字${title ? `（现在 ${title.length} 字）` : ''}`}
                  error={title.length > 80}
                  slotProps={{ input: { disableUnderline: true } }} sx={filledFieldSx} />
              </Grid>
            </Grid>

            <Typography variant="caption" color="text.secondary">
              任务交给自动搬运服务排队执行（和频道扫描同一条队列，不会两边同时压视频），处理参数用「自动搬运 › 处理与投稿」里的预设。
              现在：<Box component="span" sx={{ color: mover.color, fontWeight: 700 }}>{mover.label}</Box>
              {mover.detail ? ` · ${mover.detail}` : ''}
            </Typography>
            {automationStatus && !automationStatus.mover.online && (
              <Alert severity="warning">
                自动搬运服务没在运行，任务会一直排队，直到它启动（看「自动搬运」页的说明）。
              </Alert>
            )}
            {accountWarning && (
              <Alert severity="error" action={<Link component="button" onClick={() => onNavigate('automation')}>去登录</Link>}>
                {accountWarning}
              </Alert>
            )}
          </Box>
        )}
      </Paper>

      <Button
        variant="contained"
        size="large"
        // 投稿任务是排队执行的，前一个还没完也可以接着提交；「仅生成」一次只跑一个
        disabled={(!publish && busy) || urlInvalid || (publish && title.length > 80)}
        onClick={submit}
        endIcon={publish ? <SendIcon /> : <ZapIcon />}
        sx={{
          py: 3,
          px: 12,
          fontSize: '1.5rem',
          fontWeight: 900,
          fontStyle: 'italic',
          textTransform: 'uppercase',
          boxShadow: '0 20px 50px rgba(59, 130, 246, 0.3)',
          transition: 'all 0.3s ease',
          '&:hover': {
            transform: 'translateY(-5px)',
            boxShadow: '0 30px 60px rgba(59, 130, 246, 0.4)',
          }
        }}
      >
        {publish ? (busy ? '加入投稿队列' : '生成并投稿') : busy ? 'Processing...' : 'Engage Engine'}
      </Button>
    </Box>
  );
};

export default TaskPanel;
