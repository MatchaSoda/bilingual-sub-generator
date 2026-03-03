import React, { useState, useEffect, useRef, useMemo } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import Slider from '@mui/material/Slider';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';

import PaletteIcon from '@mui/icons-material/Palette';
import TypeIcon from '@mui/icons-material/TextFields';
import ActivityIcon from '@mui/icons-material/FlashOn';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';

import SubtitlesOctopus from 'libass-wasm';

interface StyleSliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (value: number | number[]) => void;
}

const StyleSlider = ({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange,
}: StyleSliderProps) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}
    >
      <Typography
        sx={{
          fontSize: 10,
          fontWeight: 900,
          color: 'text.secondary',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </Typography>
      <Typography
        sx={{
          fontSize: 11,
          fontWeight: 'bold',
          color: 'secondary.main',
          fontFamily: 'monospace',
        }}
      >
        {value}
        {unit}
      </Typography>
    </Box>
    <Slider
      size="small"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e, v) => onChange(v)}
      color="secondary"
      sx={{ py: 0.5 }}
    />
  </Box>
);

const DesignPanel = ({
  form,
  setForm,
}: {
  form: any;
  setForm: (form: any) => void;
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<any>(null);
  const [engineReady, setEngineReady] = useState(false);
  const [previewBg, setPreviewBg] = useState<'light' | 'dark'>('light');

  const assContent = useMemo(() => {
    const f = form;
    const m_alpha = Math.floor((1 - f.font_alpha / 100) * 255)
      .toString(16)
      .padStart(2, '0')
      .toUpperCase();
    const mo_alpha = Math.floor((1 - f.outline_alpha / 100) * 255)
      .toString(16)
      .padStart(2, '0')
      .toUpperCase();
    const fs_alpha = Math.floor((1 - (f.sub_alpha || 100) / 100) * 255)
      .toString(16)
      .padStart(2, '0')
      .toUpperCase();
    const os_alpha = Math.floor((1 - (f.outline_sub_alpha || 100) / 100) * 255)
      .toString(16)
      .padStart(2, '0')
      .toUpperCase();

    const m_v = Math.floor((f.main_bottom / 100) * 1080);
    const s_v = Math.floor((f.sub_bottom / 100) * 1080);
    const f_v = m_v;

    return `[Script Info]
Title: Physic Preview
Script Type: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,${f.font_size_main},&H${m_alpha}FFFFFF,&H000000FF,&H${mo_alpha}000000,&H90000000,${f.font_weight > 500 ? 1 : 0},0,0,0,100,100,0,0,1,${f.outline_main},${f.shadow_main},2,10,10,${m_v},1
Style: Sub,Arial,${f.font_size_sub},&H${fs_alpha}00FFFF,&H000000FF,&H${os_alpha}000000,&H90000000,${f.font_weight_sub > 500 ? 1 : 0},0,0,0,100,100,0,0,1,${f.outline_sub},${f.shadow_sub},2,10,10,${s_v},1
Style: Furi,Arial,${Math.floor(f.font_size_main * 0.4)},&H${m_alpha}FFFFFF,&H000000FF,&H${mo_alpha}000000,&H90000000,${f.font_weight > 500 ? 1 : 0},0,0,0,100,100,0,0,1,1.5,${f.shadow_main},2,10,10,${f_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,10:00:00.00,Main,,0,0,0,,私の名前は抹茶です
Dialogue: 1,0:00:00.00,10:00:00.00,Sub,,0,0,0,,我的名字是抹茶
Dialogue: 0,0:00:00.00,10:00:00.00,Furi,,0,0,0,,わたし            なまえ               まっちゃ                 \u3000
`;
  }, [form]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const canvas = document.createElement('canvas');
    canvas.width = 1920;
    canvas.height = 1080;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.objectFit = 'contain';
    canvas.style.position = 'absolute';
    canvas.style.top = '0';
    canvas.style.left = '0';
    canvas.style.zIndex = '10000';
    canvas.style.pointerEvents = 'none';
    container.appendChild(canvas);

    let subInstance = null;
    try {
      console.log('JASSUB: Initializing with Dynamic Canvas...');
      var options = {
        canvas: canvas,
        subContent: assContent,
        fonts: [
          '/fonts/NotoSansCJK-Regular.ttc',
          '/fonts/NotoSans-Regular.ttf',
        ],
      };
      subInstance = new SubtitlesOctopus(options);
      subInstance.setCurrentTime(0);
      instanceRef.current = subInstance;
      console.log('enging setCurrentTime!!');
      setEngineReady(true);
    } catch (e) {
      console.error('Core Init Failed:', e);
    }
    return () => {
      console.log('destroy');
      if (subInstance) {
        subInstance.dispose();
        instanceRef.current = null;
        setEngineReady(false);
      }
      if (container.contains(canvas)) {
        container.removeChild(canvas);
      }
    };
  }, []);

  useEffect(() => {
    if (engineReady && instanceRef.current) {
      const subInstance = instanceRef.current;
      const update = async () => {
        if (!subInstance) {
          console.log();
          return;
        }
        await subInstance.setTrack(assContent);
        await subInstance.render();
      };
      const timer = setTimeout(update, 10);
      return () => clearTimeout(timer);
    }
  }, [assContent, engineReady]);

  return (
    <Box
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        animate: 'fadeIn 0.5s ease-out',
        overflow: 'hidden',
      }}
    >
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
          padding: '0 8px',
        }}
      >
        <Box>
          <Typography
            variant="h5"
            sx={{
              fontWeight: 900,
              display: 'flex',
              alignItems: 'center',
              gap: 2,
              color: 'white',
            }}
          >
            <PaletteIcon sx={{ color: 'secondary.main' }} /> 视觉实验室
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <IconButton
            size="small"
            onClick={() =>
              setPreviewBg(previewBg === 'light' ? 'dark' : 'light')
            }
            sx={{ color: 'text.secondary' }}
          >
            {previewBg === 'light' ? <Brightness4Icon /> : <Brightness7Icon />}
          </IconButton>
          <Chip
            icon={
              engineReady ? (
                <ActivityIcon sx={{ fontSize: 14 }} />
              ) : (
                <CircularProgress size={14} />
              )
            }
            label={engineReady ? 'CORE ACTIVE' : 'BOOTING...'}
            color={engineReady ? 'success' : 'error'}
            variant="outlined"
            size="small"
            sx={{
              fontWeight: 900,
              letterSpacing: 1,
              textTransform: 'uppercase',
              fontSize: 10,
            }}
          />
        </Box>
      </header>

      <Box
        sx={{
          flex: 1,
          display: 'flex',
          gap: 4,
          minHeight: 0,
          alignItems: 'stretch',
        }}
      >
        <Box
          sx={{
            flex: 3,
            display: 'flex',
            flexDirection: 'column',
            minWidth: 0,
          }}
        >
          <Paper
            elevation={0}
            sx={{
              flex: 1,
              bgcolor: 'rgba(255, 255, 255, 0.02)',
              borderRadius: 1.5,
              border: '1px solid rgba(255, 255, 255, 0.05)',
              p: 4,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
            }}
          >
            <Box
              ref={containerRef}
              sx={{
                width: '100%',
                aspectRatio: '16/9',
                bgcolor: previewBg === 'light' ? '#fdf6e3' : '#0a0c14',
                borderRadius: 2,
                border:
                  previewBg === 'light'
                    ? '1px solid rgba(0,0,0,0.1)'
                    : '1px solid rgba(255,255,255,0.1)',
                position: 'relative',
                overflow: 'hidden',
                transition: 'background-color 0.3s ease',
                boxShadow: '0 30px 60px rgba(0,0,0,0.6)',
              }}
            ></Box>
          </Paper>
        </Box>

        <Box
          sx={{
            width: '360px',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
          }}
        >
          <Paper
            elevation={0}
            sx={{
              flex: 1,
              bgcolor: 'rgba(255, 255, 255, 0.03)',
              borderRadius: 1.5,
              border: '1px solid rgba(255, 255, 255, 0.05)',
              p: 3,
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              '&::-webkit-scrollbar': { width: 6 },
              '&::-webkit-scrollbar-thumb': {
                bgcolor: 'rgba(255,255,255,0.05)',
                borderRadius: 3,
              },
            }}
          >
            <Box>
              <Typography
                variant="overline"
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  fontWeight: 900,
                  color: 'primary.main',
                  mb: 2,
                }}
              >
                <TypeIcon sx={{ fontSize: 16 }} /> 原文图层 (Main)
              </Typography>
              <Box
                sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3 }}
              >
                <StyleSlider
                  label="字号"
                  value={form.font_size_main}
                  min={10}
                  max={150}
                  onChange={(v) => setForm({ ...form, font_size_main: v })}
                  unit="px"
                />
                <StyleSlider
                  label="底距"
                  value={form.main_bottom}
                  min={0}
                  max={100}
                  step={0.1}
                  onChange={(v) => setForm({ ...form, main_bottom: v })}
                  unit="%"
                />
                <StyleSlider
                  label="描边"
                  value={form.outline_main}
                  min={0}
                  max={15}
                  step={0.5}
                  onChange={(v) => setForm({ ...form, outline_main: v })}
                />
                <StyleSlider
                  label="阴影"
                  value={form.shadow_main}
                  min={0}
                  max={15}
                  step={0.5}
                  onChange={(v) => setForm({ ...form, shadow_main: v })}
                />
                <StyleSlider
                  label="不透明度"
                  value={form.font_alpha}
                  min={0}
                  max={100}
                  onChange={(v) => setForm({ ...form, font_alpha: v })}
                  unit="%"
                />
                <StyleSlider
                  label="字重"
                  value={form.font_weight}
                  min={100}
                  max={900}
                  step={100}
                  onChange={(v) => setForm({ ...form, font_weight: v })}
                />
              </Box>
            </Box>

            <Divider sx={{ borderColor: 'rgba(255,255,255,0.05)' }} />

            <Box>
              <Typography
                variant="overline"
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  fontWeight: 900,
                  color: 'secondary.main',
                  mb: 2,
                }}
              >
                <TypeIcon sx={{ fontSize: 16 }} /> 译文图层 (Sub)
              </Typography>
              <Box
                sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3 }}
              >
                <StyleSlider
                  label="字号"
                  value={form.font_size_sub}
                  min={10}
                  max={150}
                  onChange={(v) => setForm({ ...form, font_size_sub: v })}
                  unit="px"
                />
                <StyleSlider
                  label="底距"
                  value={form.sub_bottom}
                  min={0}
                  max={100}
                  step={0.1}
                  onChange={(v) => setForm({ ...form, sub_bottom: v })}
                  unit="%"
                />
                <StyleSlider
                  label="描边"
                  value={form.outline_sub}
                  min={0}
                  max={15}
                  step={0.5}
                  onChange={(v) => setForm({ ...form, outline_sub: v })}
                />
                <StyleSlider
                  label="阴影"
                  value={form.shadow_sub}
                  min={0}
                  max={15}
                  step={0.5}
                  onChange={(v) => setForm({ ...form, shadow_sub: v })}
                />
                <StyleSlider
                  label="不透明度"
                  value={form.sub_alpha || 100}
                  min={0}
                  max={100}
                  onChange={(v) => setForm({ ...form, sub_alpha: v })}
                  unit="%"
                />
                <StyleSlider
                  label="字重"
                  value={form.font_weight_sub || 400}
                  min={100}
                  max={900}
                  step={100}
                  onChange={(v) => setForm({ ...form, font_weight_sub: v })}
                />
              </Box>
            </Box>
          </Paper>
        </Box>
      </Box>
    </Box>
  );
};

export default DesignPanel;
