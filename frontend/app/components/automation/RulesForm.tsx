import React from 'react';
import Paper from '@mui/material/Paper';
import Grid from '@mui/material/Grid';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';

import ScheduleIcon from '@mui/icons-material/Schedule';
import HistoryToggleIcon from '@mui/icons-material/HistoryToggleOff';
import CleanIcon from '@mui/icons-material/CleaningServices';

import { AutomationConfig } from '../../../src/api';
import { cardSx } from '../../../src/automation';
import { NumberField, SectionTitle } from './fields';

interface RulesFormProps {
  draft: AutomationConfig;
  errors: Record<string, string>;
  onChange: (patch: (draft: AutomationConfig) => AutomationConfig) => void;
}

// 扫描节奏、起点水位、定期清理（docs/RUNBOOK.md §4）
const RulesForm = ({ draft, errors, onChange }: RulesFormProps) => {
  const set = (key: keyof AutomationConfig, value: any) => onChange((d) => ({ ...d, [key]: value }));
  const setIn = (section: 'backfill' | 'cleanup', key: string, value: any) =>
    onChange((d) => ({ ...d, [section]: { ...(d[section] as any), [key]: value } }));
  const minutes = draft.check_interval_seconds ? Math.round(draft.check_interval_seconds / 60) : null;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Paper elevation={0} sx={cardSx}>
        <SectionTitle icon={<ScheduleIcon color="primary" />} title="扫描节奏" />
        <Grid container spacing={2} sx={{ mt: 1 }}>
          <Grid size={{ xs: 12, md: 6 }}>
            <NumberField label="每隔多久扫一轮" unit="分钟" value={minutes} error={errors.check_interval_seconds}
              helper="改了从下一轮开始生效；想马上扫，用概览页的「立即扫描」"
              onChange={(v) => set('check_interval_seconds', v === null ? null : Math.round(v * 60))} />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <NumberField label="每轮看每个频道最近多少个视频" unit="个" value={draft.playlist_items}
              error={errors.playlist_items}
              helper="开大一点能在停机几天后把漏掉的补回来；只翻列表页，不怎么费请求"
              onChange={(v) => set('playlist_items', v)} />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <NumberField label="每轮最多处理几个视频" unit="个" value={draft.max_uploads_per_cycle}
              error={errors.max_uploads_per_cycle}
              helper="0 = 不限。防止停机恢复时一口气投一大堆"
              onChange={(v) => set('max_uploads_per_cycle', v)} />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <NumberField label="两次拉简介之间至少间隔" unit="秒" step={0.5}
              value={draft.description_fetch_interval_seconds}
              error={errors.description_fetch_interval_seconds}
              helper="拉简介最容易触发 YouTube 风控，拉开间隔更稳"
              onChange={(v) => set('description_fetch_interval_seconds', v)} />
          </Grid>
        </Grid>
      </Paper>

      <Paper elevation={0} sx={cardSx}>
        <SectionTitle icon={<HistoryToggleIcon color="secondary" />} title="补档范围（起点水位）" />
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          新账号第一次启动时，会把频道最近那一批存货全部投一遍。「只处理新视频」以这次部署第一次启动的时间为起点，
          更早发布的直接跳过；起点只记一次，之后重启不会推后。
        </Typography>
        <ToggleButtonGroup
          exclusive
          value={draft.backfill?.mode || 'all'}
          onChange={(_, value) => value && setIn('backfill', 'mode', value)}
          sx={{ mb: 2, flexWrap: 'wrap' }}
        >
          <ToggleButton value="all" sx={{ px: 2 }}>历史记录之外的全补（老账号）</ToggleButton>
          <ToggleButton value="since_first_start" sx={{ px: 2 }}>只处理新视频（新账号）</ToggleButton>
        </ToggleButtonGroup>
        {draft.backfill?.mode === 'since_first_start' && (
          <Box sx={{ maxWidth: 360 }}>
            <NumberField label="起点往前多算" unit="小时" value={draft.backfill?.lookback_hours}
              error={errors['backfill.lookback_hours']}
              helper="覆盖启动前刚发布、还没扫到的视频"
              onChange={(v) => setIn('backfill', 'lookback_hours', v)} />
          </Box>
        )}
        {errors['backfill.mode'] && <Typography color="error" variant="caption">{errors['backfill.mode']}</Typography>}
      </Paper>

      <Paper elevation={0} sx={cardSx}>
        <SectionTitle icon={<CleanIcon color="secondary" />} title="定期清理" />
        <Grid container spacing={2} sx={{ mt: 1 }}>
          <Grid size={{ xs: 12, md: 6 }}>
            <NumberField label="媒体文件保留" unit="天" value={draft.cleanup?.keep_days} error={errors['cleanup.keep_days']}
              helper="每轮开头删掉更早的下载缓存和搬运成品（已经投到 B 站）。手动制作的成品不删。0 = 不清理"
              onChange={(v) => setIn('cleanup', 'keep_days', v)} />
          </Grid>
        </Grid>
      </Paper>
    </Box>
  );
};

export default RulesForm;
