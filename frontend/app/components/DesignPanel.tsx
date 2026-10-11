import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import Slider from '@mui/material/Slider';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import CircularProgress from '@mui/material/CircularProgress';
import Button from '@mui/material/Button';
import Tooltip from '@mui/material/Tooltip';
import Snackbar from '@mui/material/Snackbar';
import TextField from '@mui/material/TextField';
import MenuItem from '@mui/material/MenuItem';
import Alert from '@mui/material/Alert';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';

import PaletteIcon from '@mui/icons-material/Palette';
import TypeIcon from '@mui/icons-material/TextFields';
import SendIcon from '@mui/icons-material/Send';
import CheckIcon from '@mui/icons-material/CheckCircleOutline';
import ColorizeIcon from '@mui/icons-material/Colorize';

import {
  automationApi, errorMessage, PreviewBackground, PreviewRequest, SubtitleFont, SubtitleStyle, subtitleApi,
} from '../../src/api';
import { filledFieldSx, pickStyle, sameStyle } from '../../src/automation';

interface StyleSliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (value: number) => void;
}

const labelSx = { fontSize: 10, fontWeight: 900, color: 'text.secondary', textTransform: 'uppercase' };
const valueSx = { fontSize: 11, fontWeight: 'bold', color: 'secondary.main', fontFamily: 'monospace' };

const StyleSlider = ({ label, value, min, max, step = 1, unit = '', onChange }: StyleSliderProps) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Typography sx={labelSx}>{label}</Typography>
      <Typography sx={valueSx}>{value}{unit}</Typography>
    </Box>
    <Slider size="small" min={min} max={max} step={step} value={value}
      onChange={(_, v) => onChange(v as number)} color="secondary" sx={{ py: 0.5 }} />
  </Box>
);

// libass 只分常规和粗体：字重大于 500 就是粗体（subtitle_generator.py），所以只给两档
const WeightField = ({ value, onChange }: { value: number; onChange: (v: number) => void }) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
    <Typography sx={labelSx}>字重</Typography>
    <ToggleButtonGroup size="small" exclusive fullWidth value={value > 500 ? 700 : 400}
      onChange={(_, v) => { if (v !== null) onChange(v); }}>
      <ToggleButton value={400} sx={{ py: 0.25, fontSize: 11 }}>常规</ToggleButton>
      <ToggleButton value={700} sx={{ py: 0.25, fontSize: 11, fontWeight: 900 }}>粗体</ToggleButton>
    </ToggleButtonGroup>
  </Box>
);

// 字幕常用的几种颜色；别的颜色用最后那个取色器
const TEXT_COLORS = [
  { value: '#FFFFFF', name: '白' }, { value: '#FFFF00', name: '黄' }, { value: '#FFE16B', name: '暖黄' },
  { value: '#9CDCFE', name: '浅蓝' }, { value: '#FFB6C8', name: '粉' }, { value: '#B6F2C1', name: '浅绿' },
  { value: '#000000', name: '黑' },
];
const OUTLINE_COLORS = [
  { value: '#000000', name: '黑' }, { value: '#FFFFFF', name: '白' }, { value: '#1F3A93', name: '深蓝' },
  { value: '#3A3A3A', name: '深灰' }, { value: '#8B1E3F', name: '酒红' }, { value: '#14532D', name: '墨绿' },
];

const swatchSx = (color: string, selected: boolean) => ({
  width: 22, height: 22, p: 0, borderRadius: '50%', cursor: 'pointer', bgcolor: color,
  border: '1px solid rgba(255,255,255,0.3)',
  boxShadow: selected ? '0 0 0 2px #0b0f19, 0 0 0 4px #14b8a6' : 'none',
  transition: 'box-shadow 0.15s ease',
});

const ColorField = ({ label, value, presets, onChange }: {
  label: string; value: string; presets: { value: string; name: string }[]; onChange: (color: string) => void;
}) => {
  const current = (value || '').toUpperCase();
  const custom = !presets.some((preset) => preset.value === current);
  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography sx={labelSx}>{label}</Typography>
        <Typography sx={valueSx}>{current}</Typography>
      </Box>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        {presets.map((preset) => (
          <Tooltip key={preset.value} title={`${preset.name} ${preset.value}`}>
            <Box component="button" type="button" aria-label={`${label}：${preset.name}`} onClick={() => onChange(preset.value)}
              sx={swatchSx(preset.value, preset.value === current)} />
          </Tooltip>
        ))}
        <Tooltip title="自定义颜色">
          <Box component="label" aria-label={`${label}：自定义`} sx={{
            ...swatchSx(current, custom), position: 'relative', display: 'inline-flex', alignItems: 'center',
            justifyContent: 'center', bgcolor: custom ? current : 'transparent',
            background: custom ? current : 'conic-gradient(#f43f5e, #f59e0b, #84cc16, #06b6d4, #6366f1, #d946ef, #f43f5e)',
          }}>
            {!custom && <ColorizeIcon sx={{ fontSize: 12, color: 'white', filter: 'drop-shadow(0 0 1px black)' }} />}
            <input type="color" value={current || '#FFFFFF'} onChange={(e) => onChange(e.target.value.toUpperCase())}
              style={{ position: 'absolute', inset: 0, opacity: 0, width: '100%', height: '100%', cursor: 'pointer' }} />
          </Box>
        </Tooltip>
      </Box>
    </Box>
  );
};

const FontField = ({ label, value, fonts, onChange }: {
  label: string; value: string; fonts: SubtitleFont[]; onChange: (family: string) => void;
}) => (
  <TextField select fullWidth variant="filled" size="small" label={label}
    value={fonts.some((font) => font.family === value) ? value : ''}
    onChange={(e) => onChange(e.target.value)} sx={filledFieldSx}
    slotProps={{
      input: { disableUnderline: true } as any,
      select: { renderValue: (family: unknown) => fonts.find((font) => font.family === family)?.label || String(family) },
    }}>
    {fonts.map((font) => (
      <MenuItem key={font.family} value={font.family} disabled={font.installed === false}>
        <Box>
          <Typography sx={{ fontWeight: 700, fontSize: 14 }}>{font.label}</Typography>
          <Typography variant="caption" color="text.secondary">
            {font.installed === false ? '服务器上没装这个字体' : font.note || font.family}
          </Typography>
        </Box>
      </MenuItem>
    ))}
  </TextField>
);

// 两层字幕的控件。main 是日文原文（振假名跟着它的字体和颜色），sub 是中文译文
const LAYERS = [
  {
    title: '日文 · 原文', color: 'primary.main', lang: 'ja', font: 'font_main', textColor: 'color_main',
    outlineColor: 'outline_color_main', size: 'font_size_main', bottom: 'main_bottom', outline: 'outline_main',
    shadow: 'shadow_main', alpha: 'font_alpha', weight: 'font_weight', defaultWeight: 700,
  },
  {
    title: '中文 · 译文', color: 'secondary.main', lang: 'zh', font: 'font_sub', textColor: 'color_sub',
    outlineColor: 'outline_color_sub', size: 'font_size_sub', bottom: 'sub_bottom', outline: 'outline_sub',
    shadow: 'shadow_sub', alpha: 'sub_alpha', weight: 'font_weight_sub', defaultWeight: 400,
  },
] as const;

const BACKGROUNDS: { value: PreviewBackground; label: string }[] = [
  { value: 'dark', label: '深色' }, { value: 'light', label: '浅色' }, { value: 'video', label: '视频画面' },
];

// 预览接口按 PNG 返回，出错时响应体是 JSON，要先从 Blob 里读出来
const previewErrorMessage = async (error: any): Promise<string> => {
  const data = error?.response?.data;
  if (data instanceof Blob) {
    try {
      const body = JSON.parse(await data.text());
      const details = (body.errors || []).map((e: any) => `${e.path}：${e.message}`).join('；');
      return details ? `${body.detail}（${details}）` : body.detail || '预览渲染失败';
    } catch {
      // 不是 JSON，用下面的通用说明
    }
  }
  return errorMessage(error, '预览渲染失败');
};

const DesignPanel = ({ form, setForm }: { form: any; setForm: (form: any) => void }) => {
  const [fonts, setFonts] = useState<SubtitleFont[]>([]);
  const [fontsError, setFontsError] = useState('');
  const [sampleText, setSampleText] = useState({ main: '', sub: '' });
  const [maxTextLength, setMaxTextLength] = useState(60);
  const [mainText, setMainText] = useState('');
  const [subText, setSubText] = useState('');
  const [background, setBackground] = useState<PreviewBackground>('dark');
  const [preview, setPreview] = useState<{ url: string; source: string } | null>(null);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState('');
  // 自动搬运 / 「生成并投稿」用的字幕样式（config.json 的 processing.style 叠在默认样式上）
  const [publishStyle, setPublishStyle] = useState<SubtitleStyle | null>(null);
  const [savingStyle, setSavingStyle] = useState(false);
  const [toast, setToast] = useState('');

  useEffect(() => {
    subtitleApi.fonts()
      .then((res) => {
        setFonts(res.data.fonts);
        setSampleText(res.data.sample_text);
        setMaxTextLength(res.data.max_text_length);
      })
      .catch((e) => setFontsError(errorMessage(e, '拿不到字体列表')));
    automationApi
      .getConfig()
      .then((res) => setPublishStyle({ ...res.data.style_defaults, ...(res.data.effective.processing?.style || {}) }))
      .catch(() => setPublishStyle(null));
  }, []);

  const set = (key: string, value: number | string) => setForm({ ...form, [key]: value });
  const styleMatches = !!publishStyle && sameStyle(pickStyle(form), publishStyle);

  const applyToPublishing = async () => {
    setSavingStyle(true);
    try {
      const res = await automationApi.saveStyle(pickStyle(form));
      setPublishStyle((prev) => ({ ...(prev || {}), ...res.data.style }));
      setToast('已设为投稿样式：之后的自动搬运和「生成并投稿」都用这套字幕样式');
    } catch (e) {
      setToast(`保存失败：${errorMessage(e)}`);
    } finally {
      setSavingStyle(false);
    }
  };

  // 预览图由服务器用压制成片的同一套代码渲染（backend/services/subtitle_preview.py）。一次只发一个请求，
  // 拖滑块时中间的状态跳过，上一张回来后直接渲染最新的那个
  const request: PreviewRequest = useMemo(() => ({
    style: pickStyle(form),
    background,
    furigana: !!form.enable_furigana,
    main_text: mainText.trim() || null,
    sub_text: subText.trim() || null,
  }), [form, background, mainText, subText]);
  const requestKey = JSON.stringify(request);
  const busy = useRef(false);
  const pending = useRef<PreviewRequest | null>(null);
  const mounted = useRef(true);
  const imageUrl = useRef<string | null>(null);

  const renderPreview = useCallback(async (next: PreviewRequest) => {
    busy.current = true;
    setRendering(true);
    try {
      const res = await subtitleApi.preview(next);
      if (!mounted.current) return;
      const url = URL.createObjectURL(res.data);
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
      imageUrl.current = url;
      setPreview({ url, source: decodeURIComponent(res.headers['x-preview-source'] || '') });
      setRenderError('');
    } catch (e) {
      if (mounted.current) setRenderError(await previewErrorMessage(e));
    } finally {
      busy.current = false;
      const queued = pending.current;
      pending.current = null;
      if (queued && mounted.current) renderPreview(queued);
      else if (mounted.current) setRendering(false);
    }
  }, []);

  useEffect(() => {
    if (busy.current) pending.current = request;
    else renderPreview(request);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, renderPreview]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    };
  }, []);

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 2, overflow: 'hidden' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0, padding: '0 8px' }}>
        <Typography variant="h5" sx={{ fontWeight: 900, display: 'flex', alignItems: 'center', gap: 2, color: 'white' }}>
          <PaletteIcon sx={{ color: 'secondary.main' }} /> 视觉实验室
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Tooltip
            title={
              styleMatches
                ? '自动搬运和「生成并投稿」用的就是现在这套样式'
                : '把现在这套样式用到自动搬运和「生成并投稿」（「仅生成」一直用这里的样式）'
            }
          >
            <span>
              <Button size="small" variant={styleMatches ? 'text' : 'outlined'} color="secondary"
                disabled={styleMatches || savingStyle || !publishStyle}
                startIcon={styleMatches ? <CheckIcon /> : <SendIcon />}
                onClick={applyToPublishing} sx={{ px: 2, py: 0.75, fontWeight: 900 }}>
                {styleMatches ? '与投稿样式一致' : '设为投稿样式'}
              </Button>
            </span>
          </Tooltip>
          <ToggleButtonGroup size="small" exclusive value={background}
            onChange={(_, value) => value && setBackground(value)}>
            {BACKGROUNDS.map((bg) => (
              <ToggleButton key={bg.value} value={bg.value} sx={{ px: 1.5, py: 0.5, fontSize: 11, fontWeight: 900 }}>
                {bg.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Tooltip title="预览图由服务器用压制视频的同一套 ffmpeg、libass 和字体渲染，16:9 的视频和成片逐像素一致（只差视频压缩）">
            <Chip
              icon={rendering ? <CircularProgress size={12} color="inherit" /> : <CheckIcon sx={{ fontSize: 14 }} />}
              label={rendering ? '渲染中' : renderError ? '渲染出错' : '成片渲染'}
              color={renderError ? 'error' : 'success'} variant="outlined" size="small"
              sx={{ fontWeight: 900, letterSpacing: 1, fontSize: 10, minWidth: 92 }}
            />
          </Tooltip>
        </Box>
      </header>

      <Box sx={{ flex: 1, display: 'flex', gap: 4, minHeight: 0, alignItems: 'stretch' }}>
        <Box sx={{ flex: 3, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Paper elevation={0} sx={{
            flex: 1, bgcolor: 'rgba(255, 255, 255, 0.02)', borderRadius: 1.5, border: '1px solid rgba(255, 255, 255, 0.05)',
            p: 4, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2, overflow: 'hidden',
          }}>
            <Box sx={{
              width: '100%', aspectRatio: '16/9', position: 'relative', overflow: 'hidden', borderRadius: 2,
              bgcolor: '#0a0c14', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 30px 60px rgba(0,0,0,0.6)',
            }}>
              {preview && (
                <img src={preview.url} alt="字幕预览（成片渲染）"
                  style={{ width: '100%', height: '100%', display: 'block', objectFit: 'contain' }} />
              )}
              {!preview && !renderError && (
                <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <CircularProgress color="secondary" />
                </Box>
              )}
              {renderError && (
                <Alert severity="error" sx={{ position: 'absolute', left: 16, right: 16, bottom: 16 }}>{renderError}</Alert>
              )}
            </Box>
            <Box sx={{ display: 'flex', gap: 2 }}>
              <TextField fullWidth size="small" variant="filled" label="预览日文" value={mainText}
                placeholder={sampleText.main} onChange={(e) => setMainText(e.target.value)} sx={filledFieldSx}
                slotProps={{ input: { disableUnderline: true } as any, htmlInput: { maxLength: maxTextLength } }} />
              <TextField fullWidth size="small" variant="filled" label="预览中文" value={subText}
                placeholder={sampleText.sub} onChange={(e) => setSubText(e.target.value)} sx={filledFieldSx}
                slotProps={{ input: { disableUnderline: true } as any, htmlInput: { maxLength: maxTextLength } }} />
            </Box>
            <Typography variant="caption" color="text.secondary">
              这张图是服务器用压制视频的同一套代码、同一批字体渲染的 1920×1080 画面，16:9 的视频成片就是这个样子
              （只多了视频压缩；竖屏等别的比例排版会不一样）。
              {form.enable_furigana ? '振假名按「系统设置」打开。' : '「系统设置」里关了振假名。'}
              {background === 'video' && preview?.source ? ` 背景是「${preview.source}」的一帧。` : ''}
            </Typography>
          </Paper>
        </Box>

        <Box sx={{ width: '360px', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
          <Paper elevation={0} sx={{
            flex: 1, bgcolor: 'rgba(255, 255, 255, 0.03)', borderRadius: 1.5, border: '1px solid rgba(255, 255, 255, 0.05)',
            p: 3, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4,
            '&::-webkit-scrollbar': { width: 6 },
            '&::-webkit-scrollbar-thumb': { bgcolor: 'rgba(255,255,255,0.05)', borderRadius: 3 },
          }}>
            {fontsError && <Alert severity="warning">{fontsError}</Alert>}
            {LAYERS.map((layer, index) => (
              <React.Fragment key={layer.font}>
                {index > 0 && <Divider sx={{ borderColor: 'rgba(255,255,255,0.05)' }} />}
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <Typography variant="overline" sx={{
                    display: 'flex', alignItems: 'center', gap: 1, fontWeight: 900, color: layer.color, lineHeight: 1,
                  }}>
                    <TypeIcon sx={{ fontSize: 16 }} /> {layer.title}
                  </Typography>
                  <FontField label="字体" value={form[layer.font]} fonts={fonts.filter((font) => font.lang === layer.lang)}
                    onChange={(family) => set(layer.font, family)} />
                  <ColorField label="文字颜色" value={form[layer.textColor]} presets={TEXT_COLORS}
                    onChange={(color) => set(layer.textColor, color)} />
                  <ColorField label="描边颜色" value={form[layer.outlineColor]} presets={OUTLINE_COLORS}
                    onChange={(color) => set(layer.outlineColor, color)} />
                  <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3 }}>
                    <StyleSlider label="字号" value={form[layer.size]} min={10} max={150}
                      onChange={(v) => set(layer.size, v)} />
                    <StyleSlider label="底距" value={form[layer.bottom]} min={0} max={100} step={0.1} unit="%"
                      onChange={(v) => set(layer.bottom, v)} />
                    <StyleSlider label="描边" value={form[layer.outline]} min={0} max={15} step={0.5}
                      onChange={(v) => set(layer.outline, v)} />
                    <StyleSlider label="阴影" value={form[layer.shadow]} min={0} max={15} step={0.5}
                      onChange={(v) => set(layer.shadow, v)} />
                    <StyleSlider label="不透明度" value={form[layer.alpha] ?? 100} min={0} max={100} unit="%"
                      onChange={(v) => set(layer.alpha, v)} />
                    <WeightField value={form[layer.weight] ?? layer.defaultWeight} onChange={(v) => set(layer.weight, v)} />
                  </Box>
                </Box>
              </React.Fragment>
            ))}
          </Paper>
        </Box>
      </Box>
      <Snackbar open={!!toast} autoHideDuration={4000} onClose={() => setToast('')} message={toast}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }} />
    </Box>
  );
};

export default DesignPanel;
