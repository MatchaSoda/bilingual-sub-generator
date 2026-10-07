import React from 'react';
import Paper from '@mui/material/Paper';
import Grid from '@mui/material/Grid';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import Autocomplete from '@mui/material/Autocomplete';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';

import TuneIcon from '@mui/icons-material/Tune';
import PaletteIcon from '@mui/icons-material/Palette';
import UploadIcon from '@mui/icons-material/CloudUpload';
import ImportIcon from '@mui/icons-material/Input';

import { AutomationConfig, AutomationConfigResponse } from '../../../src/api';
import { cardSx, filledFieldSx, pickStyle, sameStyle, STYLE_KEYS } from '../../../src/automation';
import { NumberField, SectionTitle, SwitchRow, TextInput } from './fields';

const STYLE_LABELS: Record<string, string> = {
  font_size_main: '原文字号', main_bottom: '原文底距', font_alpha: '原文不透明度', outline_alpha: '原文描边不透明度',
  font_weight: '原文字重', outline_main: '原文描边', shadow_main: '原文阴影',
  font_size_sub: '译文字号', sub_bottom: '译文底距', sub_alpha: '译文不透明度', outline_sub_alpha: '译文描边不透明度',
  font_weight_sub: '译文字重', outline_sub: '译文描边', shadow_sub: '译文阴影',
};

const WHISPER_LABELS: Record<string, string> = {
  'large-v3-turbo': 'Large-V3-Turbo（推荐）', 'large-v3': 'Large-V3（日语易缺标点）', medium: 'Medium',
  small: 'Small（快，错得多）', base: 'Base', tiny: 'Tiny',
};

interface ProcessingFormProps {
  draft: AutomationConfig;
  meta: AutomationConfigResponse;
  errors: Record<string, string>;
  webForm: Record<string, any>;
  onChange: (patch: (draft: AutomationConfig) => AutomationConfig) => void;
}

const SAMPLE = {
  title: '【台风27号】发达北上 周初小笠原群岛恐有狂风暴雨',
  original_title: '【台風27号】発達しながら北上の見込み 週明けは小笠原諸島で大荒れのおそれ',
  url: 'https://www.youtube.com/watch?v=yIBd28AAJ2Y',
  video_id: 'yIBd28AAJ2Y',
};
const renderTemplate = (template: string) =>
  (template || '').replace(/\{(\w+)\}/g, (all, key) => (SAMPLE as any)[key] ?? all);

// 自动搬运和「生成并投稿」共用的处理参数与投稿设置
const ProcessingForm = ({ draft, meta, errors, webForm, onChange }: ProcessingFormProps) => {
  const processing = draft.processing || ({} as AutomationConfig['processing']);
  const upload = draft.upload || ({} as AutomationConfig['upload']);
  const setProcessing = (key: string, value: any) =>
    onChange((d) => ({ ...d, processing: { ...d.processing, [key]: value } }));
  const setUpload = (key: string, value: any) => onChange((d) => ({ ...d, upload: { ...d.upload, [key]: value } }));

  const style = processing.style || {};
  const customKeys = STYLE_KEYS.filter((key) => style[key] !== undefined && style[key] !== meta.style_defaults[key]);
  const webStyle = pickStyle(webForm);
  const effectiveStyle = { ...meta.style_defaults, ...style };
  const webMatches = sameStyle(webStyle, effectiveStyle);

  // 把「系统设置」和「视觉实验室」里正在用的参数整套搬过来（只改草稿，保存才生效）
  const importFromWeb = () =>
    onChange((d) => ({
      ...d,
      processing: {
        ...d.processing,
        whisper_model: meta.options.whisper_models.includes(webForm.model) ? webForm.model : d.processing.whisper_model,
        gemini_model: webForm.translation_model || d.processing.gemini_model,
        segment_mode: webForm.segment_mode || d.processing.segment_mode,
        enable_furigana: !!webForm.enable_furigana,
        fix_source_text: !!webForm.fix_source,
        style: webStyle,
      },
    }));

  const titlePreview = renderTemplate(upload.title_template).slice(0, 80);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <Paper elevation={0} sx={cardSx}>
        <SectionTitle icon={<TuneIcon color="primary" />} title="处理参数">
          <Button size="small" startIcon={<ImportIcon />} onClick={importFromWeb} sx={{ px: 1.5, py: 0.5 }}>
            导入网页当前设置
          </Button>
        </SectionTitle>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          自动搬运和「生成并投稿」都按这里处理；「系统设置」「视觉实验室」只管「仅生成」的任务。
          「导入网页当前设置」把那边的模型、开关和字幕样式整套搬过来，保存后生效。
        </Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 4 }}>
            <TextField select fullWidth variant="filled" label="语音识别模型" value={processing.whisper_model || ''}
              error={!!errors['processing.whisper_model']} helperText={errors['processing.whisper_model']}
              onChange={(e) => setProcessing('whisper_model', e.target.value)}
              slotProps={{ input: { disableUnderline: true } as any }} sx={filledFieldSx}>
              {meta.options.whisper_models.map((m) => <MenuItem key={m} value={m}>{WHISPER_LABELS[m] || m}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Autocomplete
              freeSolo
              options={meta.options.gemini_models}
              value={processing.gemini_model || ''}
              onInputChange={(_, value) => setProcessing('gemini_model', value)}
              renderInput={(params) => (
                <TextField {...params} InputProps={{ ...params.InputProps, disableUnderline: true }}
                  variant="filled" label="翻译模型（Gemini）" sx={filledFieldSx}
                  error={!!errors['processing.gemini_model']}
                  helperText={errors['processing.gemini_model'] || '可以直接输入别的模型名'} />
              )}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <TextField select fullWidth variant="filled" label="断句" value={processing.segment_mode || 'rule'}
              onChange={(e) => setProcessing('segment_mode', e.target.value)}
              slotProps={{ input: { disableUnderline: true } as any }} sx={filledFieldSx}>
              <MenuItem value="rule">规则断句（离线，默认）</MenuItem>
              <MenuItem value="llm">LLM 语义断句（Gemini）</MenuItem>
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <NumberField label="每批翻译多少行" value={processing.translation_batch_size}
              error={errors['processing.translation_batch_size']}
              helper="大一点上下文更连贯；模型偶尔会合并行，数量对不上会自动对半拆"
              onChange={(v) => setProcessing('translation_batch_size', v)} />
          </Grid>
          <Grid size={{ xs: 12, md: 8 }}>
            <Stack spacing={1.5} sx={{ pt: 0.5 }}>
              <SwitchRow label="日语假名注音" description="在日文字幕上方加振假名" checked={processing.enable_furigana}
                onChange={(v) => setProcessing('enable_furigana', v)} />
              <SwitchRow label="翻译视频标题" description="B 站标题和成品文件名用中文" checked={processing.translate_title}
                onChange={(v) => setProcessing('translate_title', v)} />
              <SwitchRow label="AI 原文纠错" description="翻译时顺带修正语音识别的错字" checked={processing.fix_source_text}
                onChange={(v) => setProcessing('fix_source_text', v)} />
            </Stack>
          </Grid>
        </Grid>
      </Paper>

      <Paper elevation={0} sx={cardSx}>
        <SectionTitle icon={<PaletteIcon color="secondary" />} title="字幕样式">
          <Chip size="small" variant="outlined" sx={{ fontWeight: 700 }}
            label={customKeys.length ? `自定义 ${customKeys.length} 项` : '默认样式'}
            color={customKeys.length ? 'secondary' : 'default'} />
        </SectionTitle>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          在「视觉实验室」调好后点「设为投稿样式」，或者在这里导入。
          {webMatches ? ' 视觉实验室当前的样式和投稿样式一致。' : ' 视觉实验室当前的样式和投稿样式不一样。'}
        </Typography>
        {customKeys.length > 0 && (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
            {customKeys.map((key) => (
              <Chip key={key} size="small" label={`${STYLE_LABELS[key] || key} ${style[key]}（默认 ${meta.style_defaults[key]}）`} />
            ))}
          </Box>
        )}
        <Stack direction="row" spacing={1}>
          <Button size="small" variant="outlined" disabled={webMatches}
            onClick={() => setProcessing('style', webStyle)}>导入视觉实验室的样式</Button>
          <Button size="small" disabled={!customKeys.length} onClick={() => setProcessing('style', {})}>恢复默认样式</Button>
        </Stack>
        {errors['processing.style'] && <Typography color="error" variant="caption">{errors['processing.style']}</Typography>}
      </Paper>

      <Paper elevation={0} sx={cardSx}>
        <SectionTitle icon={<UploadIcon color="primary" />} title="投稿设置" />
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          这一段在每次投稿那一刻重新读，改完保存立刻生效，不用等下一轮（换上传线路救火用，见 RUNBOOK §5.4）。
        </Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 4 }}>
            <TextField select fullWidth variant="filled" label="上传线路" value={upload.line || ''}
              error={!!errors['upload.line']}
              helperText={errors['upload.line'] || '某条线路证书过期时 50% 投稿失败，钉一条证书干净的'}
              onChange={(e) => setUpload('line', e.target.value || null)}
              slotProps={{ input: { disableUnderline: true } as any }} sx={filledFieldSx}>
              <MenuItem value="">自动选择</MenuItem>
              {meta.options.upload_lines.map((line) => <MenuItem key={line} value={line}>{line}</MenuItem>)}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <NumberField label="投稿失败重试" unit="次" value={upload.retries} error={errors['upload.retries']}
              helper="每次换一个新的 biliup 进程" onChange={(v) => setUpload('retries', v)} />
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <NumberField label="重试间隔" unit="秒" value={upload.retry_delay_seconds}
              error={errors['upload.retry_delay_seconds']} onChange={(v) => setUpload('retry_delay_seconds', v)} />
          </Grid>
          <Grid size={12}>
            <Divider sx={{ borderColor: 'rgba(255,255,255,0.05)', my: 1 }} />
            <Typography variant="caption" color="text.secondary">
              模板里可以用：{'{title}'} 翻译后的标题、{'{original_title}'} 原标题、{'{url}'} 原视频链接、{'{video_id}'} 视频 ID
            </Typography>
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput label="B 站标题模板" value={upload.title_template} error={errors['upload.title_template']}
              helper={`预览：${titlePreview}（超过 80 字会截断）`}
              onChange={(v) => setUpload('title_template', v)} />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput label="B 站简介模板" multiline value={upload.description_template}
              error={errors['upload.description_template']}
              helper={`预览：${renderTemplate(upload.description_template).slice(0, 250)}`}
              onChange={(v) => setUpload('description_template', v)} />
          </Grid>
        </Grid>
      </Paper>
    </Box>
  );
};

export default ProcessingForm;
