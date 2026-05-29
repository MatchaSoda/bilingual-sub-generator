import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import Grid from '@mui/material/Grid';
import Switch from '@mui/material/Switch';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Divider from '@mui/material/Divider';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import InputAdornment from '@mui/material/InputAdornment';
import IconButton from '@mui/material/IconButton';

import SettingsIcon from '@mui/icons-material/Settings';
import KeyIcon from '@mui/icons-material/Key';
import SaveIcon from '@mui/icons-material/Save';
import Visibility from '@mui/icons-material/Visibility';
import VisibilityOff from '@mui/icons-material/VisibilityOff';

import { configApi } from '../../src/api';

interface SettingsPanelProps {
  form: any;
  setForm: (form: any) => void;
}

const SettingsPanel = ({ form, setForm }: SettingsPanelProps) => {
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const res = await configApi.get();
        setApiKey(res.data.google_api_keys || '');
      } catch (e) {
        console.error("Load config failed", e);
      }
    };
    loadConfig();
  }, []);

  const handleSaveKeys = async () => {
    setSaving(true);
    setStatusMsg('');
    try {
      await configApi.save(apiKey);
      setStatusMsg('API Keys saved successfully!');
      setTimeout(() => setStatusMsg(''), 3000);
    } catch (e) {
      setStatusMsg('Failed to save API Keys');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ maxWidth: 1000, mx: 'auto', display: 'flex', flexDirection: 'column', gap: 4, pt: 2, animate: 'fadeIn 0.5s ease-out' }}>
      <header>
        <Typography 
          variant="h4" 
          sx={{ 
            fontWeight: 900, 
            display: 'flex', 
            alignItems: 'center', 
            gap: 2, 
            color: 'white' 
          }}
        >
          <SettingsIcon sx={{ fontSize: 40, color: 'secondary.main' }} />
          系统设置
        </Typography>
      </header>

      <Grid container spacing={4}>
        {/* 左侧：API Key 管理 (NEW) */}
        <Grid size={{ xs: 12, md: 12 }}>
          <Paper 
            elevation={0}
            sx={{ 
              p: 4, 
              borderRadius: 2, 
              bgcolor: 'rgba(255, 255, 255, 0.03)', 
              border: '1px solid rgba(255, 255, 255, 0.05)',
              display: 'flex',
              flexDirection: 'column',
              gap: 3
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <KeyIcon color="primary" />
              <Typography variant="h6" sx={{ fontWeight: 900 }}>Gemini API Credentials</Typography>
            </Box>
            
            <Typography variant="caption" color="text.secondary">
              输入您的 Google AI (Gemini) API Key。支持多个 Key，请用逗号分隔以实现自动轮询。
            </Typography>

            <Box sx={{ display: 'flex', gap: 2 }}>
              <TextField
                fullWidth
                variant="filled"
                label="GOOGLE_API_KEYS"
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Paste keys here, separated by commas"
                sx={{ 
                  '& .MuiFilledInput-root': { 
                    borderRadius: 1.5,
                    bgcolor: 'rgba(0,0,0,0.3)',
                    '&:hover': { bgcolor: 'rgba(0,0,0,0.4)' }
                  } 
                }}
                InputProps={{
                  disableUnderline: true,
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton onClick={() => setShowKey(!showKey)} edge="end" sx={{ color: 'text.secondary' }}>
                        {showKey ? <VisibilityOff /> : <Visibility />}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
              />
              <Button 
                variant="contained" 
                size="large"
                disabled={saving}
                onClick={handleSaveKeys}
                startIcon={<SaveIcon />}
                sx={{ 
                  px: 4, 
                  fontWeight: 900, 
                  borderRadius: 2,
                  bgcolor: 'primary.main',
                  '&:hover': { bgcolor: 'primary.dark' }
                }}
              >
                {saving ? 'Saving...' : 'Save'}
              </Button>
            </Box>
            {statusMsg && (
              <Typography variant="caption" sx={{ color: statusMsg.includes('success') ? 'secondary.main' : 'error.main', fontWeight: 700 }}>
                {statusMsg}
              </Typography>
            )}
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <Paper 
            elevation={0}
            sx={{ 
              p: 4, 
            borderRadius: 1.5, 
              bgcolor: 'rgba(255, 255, 255, 0.03)', 
              border: '1px solid rgba(255, 255, 255, 0.05)',
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              gap: 4
            }}
          >
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>日语假名 (Furigana)</Typography>
                <Typography variant="caption" color="text.secondary">在日文字幕上方添加平假名注音</Typography>
              </Box>
              <Switch 
                checked={form.enable_furigana} 
                onChange={(e)=>setForm({...form, enable_furigana: e.target.checked})} 
                color="secondary"
              />
            </Stack>
            
            <Divider sx={{ borderColor: 'rgba(255,255,255,0.05)' }} />

            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>AI 原文纠错</Typography>
                <Typography variant="caption" color="text.secondary">使用 LLM 修复 ASR 识别出的拼写错误</Typography>
              </Box>
              <Switch 
                checked={form.fix_source} 
                onChange={(e)=>setForm({...form, fix_source: e.target.checked})} 
                color="secondary"
              />
            </Stack>
          </Paper>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <Paper 
            elevation={0}
            sx={{ 
              p: 4, 
            borderRadius: 1.5, 
              bgcolor: 'rgba(255, 255, 255, 0.03)', 
              border: '1px solid rgba(255, 255, 255, 0.05)',
              display: 'flex',
              flexDirection: 'column',
              gap: 4
            }}
          >
            <FormControl fullWidth variant="filled">
              <InputLabel sx={{ fontWeight: 900, textTransform: 'uppercase', fontSize: 10, letterSpacing: 1.5 }}>ASR 引擎规模</InputLabel>
              <Select
                value={form.model}
                onChange={(e)=>setForm({...form, model: e.target.value})}
                disableUnderline
                sx={{ 
                borderRadius: 3, 
                  bgcolor: 'rgba(0,0,0,0.3)', 
                  '&:hover': { bgcolor: 'rgba(0,0,0,0.4)' },
                  fontWeight: 700
                }}
              >
                <MenuItem value="tiny">Tiny (极致速度)</MenuItem>
                <MenuItem value="small">Small (性能平衡)</MenuItem>
                <MenuItem value="medium">Medium (高精准度)</MenuItem>
                <MenuItem value="large-v3-turbo">Large-V3-Turbo (推荐·快且标点完整)</MenuItem>
                <MenuItem value="large-v3">Large-V3 (最高品质·日语易缺标点)</MenuItem>
              </Select>
            </FormControl>

            <FormControl fullWidth variant="filled">
              <InputLabel sx={{ fontWeight: 900, textTransform: 'uppercase', fontSize: 10, letterSpacing: 1.5 }}>翻译引擎 (Gemini 2026 Series)</InputLabel>
              <Select
                value={form.translation_model || 'gemini-3.1-flash-lite'}
                onChange={(e)=>setForm({...form, translation_model: e.target.value})}
                disableUnderline
                sx={{ 
                borderRadius: 3, 
                  bgcolor: 'rgba(0,0,0,0.3)', 
                  '&:hover': { bgcolor: 'rgba(0,0,0,0.4)' },
                  fontWeight: 700
                }}
              >
                <MenuItem value="gemini-3.1-flash-lite">Gemini 3.1 Flash Lite (轻量默认)</MenuItem>
                <MenuItem value="gemini-3.1-pro-preview">Gemini 3.1 Pro (旗舰级推理)</MenuItem>
                <MenuItem value="gemini-3-flash-preview">Gemini 3 Flash (极速响应)</MenuItem>
                <MenuItem value="gemini-2.5-flash">Gemini 2.5 Flash (稳定版)</MenuItem>
              </Select>
            </FormControl>

            <FormControl fullWidth variant="filled">
              <InputLabel sx={{ fontWeight: 900, textTransform: 'uppercase', fontSize: 10, letterSpacing: 1.5 }}>断句模式</InputLabel>
              <Select
                value={form.segment_mode || 'rule'}
                onChange={(e)=>setForm({...form, segment_mode: e.target.value})}
                disableUnderline
                sx={{
                borderRadius: 3,
                  bgcolor: 'rgba(0,0,0,0.3)',
                  '&:hover': { bgcolor: 'rgba(0,0,0,0.4)' },
                  fontWeight: 700
                }}
              >
                <MenuItem value="rule">规则断句 (离线 · 默认)</MenuItem>
                <MenuItem value="llm">LLM 语义断句 (Gemini · 更贴句意)</MenuItem>
              </Select>
            </FormControl>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
};

export default SettingsPanel;
