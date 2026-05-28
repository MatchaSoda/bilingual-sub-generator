'use client';

import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Drawer from '@mui/material/Drawer';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Typography from '@mui/material/Typography';
import Avatar from '@mui/material/Avatar';

import VideoIcon from '@mui/icons-material/VideoLabel';
import PaletteIcon from '@mui/icons-material/Palette';
import ActivityIcon from '@mui/icons-material/Assessment';
import FolderPlayIcon from '@mui/icons-material/FolderSpecial';
import SettingsIcon from '@mui/icons-material/Settings';

import { taskApi } from '../src/api';

// 导入组件
import TaskPanel from './components/TaskPanel';
import DesignPanel from './components/DesignPanel';
import TelemetryPanel from './components/TelemetryPanel';
import LibraryPanel from './components/LibraryPanel';
import SettingsPanel from './components/SettingsPanel';


const DEFAULT_FORM = {
  url: '',
  model: 'large-v3',
  translation_model: 'gemini-3-flash-preview',
  enable_furigana: true,
  fix_source: false,
  segment_mode: 'rule',
  target_lang: 'zh-CN',
  font_size_main: 90,
  main_bottom: 0.7,
  font_alpha: 100,
  outline_alpha: 100,
  font_weight: 700,
  outline_main: 3.0,
  shadow_main: 1.5,
  font_size_sub: 75,
  sub_bottom: 92.1,
  sub_alpha: 100,
  outline_sub_alpha: 100,
  font_weight_sub: 400,
  outline_sub: 2.0,
  shadow_sub: 1.5,
};

export default function Home() {
  const [activeTab, setActiveTab] = useState('task');
  const [taskId, setTaskId] = useState('');
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('idle');
  const [form, setForm] = useState(DEFAULT_FORM);
  // console.log(form.font_size_main);
  useEffect(() => {
    // 只能在客户端运行
    const savedId = localStorage.getItem('last_task_id') || '';
    setTaskId(savedId);

    const savedForm = localStorage.getItem('matcha_config');
    if (savedForm) {
      setForm({ ...DEFAULT_FORM, ...JSON.parse(savedForm), url: '' });
    }
  }, []);

  useEffect(() => {
    if (typeof window !== 'undefined' && form !== DEFAULT_FORM) {
      const { url, ...persistData } = form;
      localStorage.setItem(
        'matcha_config',
        JSON.stringify(persistData)
      );
    }
  }, [form]);

  useEffect(() => {
    let interval;
    if (taskId && status === 'processing') {
      interval = setInterval(async () => {
        try {
          const res = await taskApi.getStatus(taskId);
          setLogs(res.data.logs || []);
          setStatus(res.data.status);
          if (res.data.status === 'completed' || res.data.status === 'failed')
            clearInterval(interval);
        } catch (e) {
          console.error('Poll fail', e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [taskId, status]);

  const startTask = async () => {
    if (!form.url) {
      alert('Please paste URL');
      return;
    }
    try {
      setStatus('processing');
      setLogs(['🚀 启动引擎...']);
      const res = await taskApi.create(form);
      setTaskId(res.data.task_id);
      localStorage.setItem('last_task_id', res.data.task_id);
      setActiveTab('logs');
    } catch (e) {
      setStatus('failed');
    }
  };

  const navItems = [
    { id: 'task', label: '制作任务', icon: <VideoIcon /> },
    { id: 'design', label: '视觉实验室', icon: <PaletteIcon /> },
    { id: 'logs', label: '实时遥测', icon: <ActivityIcon /> },
    { id: 'library', label: '媒体库', icon: <FolderPlayIcon /> },
    { id: 'settings', label: '系统设置', icon: <SettingsIcon /> },
  ];

  const drawerWidth = 260;

  return (
    <Box sx={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Sidebar */}
      <Drawer
        variant="permanent"
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: drawerWidth,
            boxSizing: 'border-box',
            borderRight: '1px solid rgba(255, 255, 255, 0.05)',
            backgroundColor: 'background.paper',
          },
        }}
      >
        <Box
          sx={{
            p: 3,
            borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
            display: 'flex',
            alignItems: 'center',
            gap: 2,
          }}
        >
          <Avatar sx={{ bgcolor: 'primary.main', fontWeight: 'bold' }}>
            🍵
          </Avatar>
          <Box>
            <Typography
              variant="h6"
              sx={{
                fontWeight: 900,
                fontStyle: 'italic',
                textTransform: 'uppercase',
                lineHeight: 1,
              }}
            >
              Matcha AI
            </Typography>
            <Typography
              variant="caption"
              sx={{
                color: 'text.secondary',
                fontWeight: 900,
                textTransform: 'uppercase',
                letterSpacing: 1.5,
              }}
            >
              Modular v1.1
            </Typography>
          </Box>
        </Box>
        <List sx={{ px: 2, mt: 2 }}>
          {navItems.map((item) => (
            <ListItem key={item.id} disablePadding sx={{ mb: 1 }}>
              <ListItemButton
                onClick={() => setActiveTab(item.id)}
                selected={activeTab === item.id}
                sx={{
                  borderRadius: 2,
                  '&.Mui-selected': {
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    color: 'primary.main',
                    '& .MuiListItemIcon-root': { color: 'primary.main' },
                    border: '1px solid rgba(59, 130, 246, 0.2)',
                  },
                  '&:hover': {
                    backgroundColor: 'rgba(255, 255, 255, 0.05)',
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
                <ListItemText
                  primary={item.label}
                  primaryTypographyProps={{
                    variant: 'caption',
                    sx: {
                      fontWeight: 900,
                      textTransform: 'uppercase',
                      letterSpacing: 1.2,
                    },
                  }}
                />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      </Drawer>

      {/* Main Content */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          height: '100vh',
          overflow: 'auto',
          position: 'relative',
          background:
            'radial-gradient(circle at top right, #0f172a 0%, #02040a 100%)',
          p: 4,
        }}
      >
        <Box sx={{ maxWidth: 1400, mx: 'auto', height: '100%' }}>
          {activeTab === 'task' && (
            <TaskPanel
              form={form}
              setForm={setForm}
              startTask={startTask}
              status={status}
              onNavigate={setActiveTab}
            />
          )}
          {activeTab === 'design' && (
            <DesignPanel form={form} setForm={setForm} />
          )}
          {activeTab === 'logs' && (
            <TelemetryPanel logs={logs} status={status} />
          )}
          {activeTab === 'library' && <LibraryPanel />}
          {activeTab === 'settings' && (
            <SettingsPanel form={form} setForm={setForm} />
          )}
        </Box>
      </Box>
    </Box>
  );
}
