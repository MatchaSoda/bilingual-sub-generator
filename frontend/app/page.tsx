'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
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
import RobotIcon from '@mui/icons-material/SmartToy';
import DotIcon from '@mui/icons-material/FiberManualRecord';

import { taskApi, automationApi, AutomationStatus, PublishRequest, errorMessage } from '../src/api';
import { syncServerTime } from '../src/automation';

// 导入组件
import TaskPanel, { TaskMode } from './components/TaskPanel';
import DesignPanel from './components/DesignPanel';
import TelemetryPanel from './components/TelemetryPanel';
import LibraryPanel from './components/LibraryPanel';
import SettingsPanel from './components/SettingsPanel';
import AutomationPanel from './components/automation/AutomationPanel';
import { describeMover } from './components/automation/StatusCard';

// 这些状态下任务还没结束，要继续轮询（Web 任务 pending/processing，投稿任务 queued/processing）
const ACTIVE_STATUSES = ['pending', 'queued', 'processing'];


const DEFAULT_FORM = {
  url: '',
  model: 'large-v3-turbo',
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
  const [task, setTask] = useState<any>(null);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [taskMode, setTaskMode] = useState<TaskMode>('generate');
  const [automationStatus, setAutomationStatus] = useState<AutomationStatus | null>(null);
  const automationDirty = useRef(false);

  // 拉一次任务状态（Web 任务或投稿任务，/api/status 两种都认）
  const fetchTask = useCallback(async (id: string) => {
    const res = await taskApi.getStatus(id);
    setTask(res.data);
    setLogs(res.data.logs || []);
    setStatus(res.data.status);
    return res.data;
  }, []);

  // console.log(form.font_size_main);
  useEffect(() => {
    // 只能在客户端运行
    const savedId = localStorage.getItem('last_task_id') || '';
    setTaskId(savedId);
    // 刷新页面后接着看上一个任务（投稿任务在 userdata 里，服务重启也还在；Web 任务重启后就没了）
    if (savedId) fetchTask(savedId).catch(() => undefined);

    const savedForm = localStorage.getItem('matcha_config');
    if (savedForm) {
      setForm({ ...DEFAULT_FORM, ...JSON.parse(savedForm), url: '' });
    }
    const savedMode = localStorage.getItem('task-mode');
    if (savedMode === 'publish' || savedMode === 'generate') setTaskMode(savedMode);
  }, [fetchTask]);

  const changeTaskMode = (mode: TaskMode) => {
    setTaskMode(mode);
    localStorage.setItem('task-mode', mode);
  };

  // 自动搬运的状态：侧边栏的小圆点、制作任务页的提示、自动搬运页都用它。看得到的页面刷得勤一点
  const refreshAutomationStatus = useCallback(async () => {
    try {
      const res = await automationApi.status();
      syncServerTime(res.data.server_time);
      setAutomationStatus(res.data);
    } catch {
      // 后端暂时连不上，下次再试
    }
  }, []);

  useEffect(() => {
    refreshAutomationStatus();
    const fast = activeTab === 'automation' || (activeTab === 'task' && taskMode === 'publish')
      || (activeTab === 'logs' && task?.kind === 'publish' && ACTIVE_STATUSES.includes(status));
    const timer = setInterval(refreshAutomationStatus, fast ? 5000 : 30000);
    return () => clearInterval(timer);
  }, [activeTab, taskMode, task?.kind, status, refreshAutomationStatus]);

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
    if (taskId && ACTIVE_STATUSES.includes(status)) {
      interval = setInterval(async () => {
        try {
          const data = await fetchTask(taskId);
          if (!ACTIVE_STATUSES.includes(data.status)) clearInterval(interval);
        } catch (e) {
          console.error('Poll fail', e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [taskId, status, fetchTask]);

  // 在遥测页打开某个任务（自动搬运页的「日志」、重试之后）
  const openTask = useCallback((id: string) => {
    setTaskId(id);
    localStorage.setItem('last_task_id', id);
    setActiveTab('logs');
    fetchTask(id).catch(() => undefined);
  }, [fetchTask]);

  const startTask = async () => {
    if (!form.url) {
      alert('Please paste URL');
      return;
    }
    try {
      setStatus('processing');
      setTask(null);
      setLogs(['🚀 启动引擎...']);
      const res = await taskApi.create(form);
      setTaskId(res.data.task_id);
      localStorage.setItem('last_task_id', res.data.task_id);
      setActiveTab('logs');
    } catch (e) {
      setStatus('failed');
    }
  };

  // 「生成并投稿」：任务进自动搬运的队列。投过稿 / 在历史记录里的视频要确认一次才强制投
  const startPublish = async (request: PublishRequest) => {
    if (!request.url) {
      alert('Please paste URL');
      return;
    }
    try {
      let res;
      try {
        res = await automationApi.createJob(request);
      } catch (e: any) {
        if (e?.response?.status !== 409) throw e;
        const question = e.response.data.reason === 'uploaded'
          ? `${e.response.data.detail}。确定要再投一次吗？`
          : `${e.response.data.detail}。确定要投稿吗？`;
        if (!confirm(question)) return;
        res = await automationApi.createJob({ ...request, force: true });
      }
      if (res.data.duplicate) alert('这个视频已经在投稿队列里了，带你去看它的进度');
      setForm({ ...form, url: '' });
      openTask(res.data.task_id);
      refreshAutomationStatus();
    } catch (e) {
      alert(`提交失败：${errorMessage(e)}`);
    }
  };

  const cancelCurrentTask = async () => {
    if (!taskId || !confirm('取消这个投稿任务？')) return;
    try {
      await automationApi.cancelJob(taskId);
    } catch (e) {
      alert(errorMessage(e));
    }
    fetchTask(taskId).catch(() => undefined);
  };

  const retryCurrentTask = async () => {
    try {
      const res = await automationApi.retryJob(taskId);
      openTask(res.data.task_id);
    } catch (e) {
      alert(errorMessage(e));
    }
  };

  // 自动搬运页有没保存的配置时，切走前确认一下（切页面会丢掉草稿）
  const navigate = (tab: string) => {
    if (tab !== activeTab && activeTab === 'automation' && automationDirty.current
      && !confirm('自动搬运的配置还没保存，离开会丢掉这些修改。确定离开？')) return;
    if (tab !== 'automation') automationDirty.current = false;
    setActiveTab(tab);
  };
  const handleAutomationDirty = useCallback((dirty: boolean) => {
    automationDirty.current = dirty;
  }, []);
  const moverSummary = describeMover(automationStatus);

  const navItems = [
    { id: 'task', label: '制作任务', icon: <VideoIcon /> },
    { id: 'automation', label: '自动搬运', icon: <RobotIcon /> },
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
                onClick={() => navigate(item.id)}
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
                {item.id === 'automation' && automationStatus && (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }} title={moverSummary.detail}>
                    <DotIcon sx={{ fontSize: 10, color: moverSummary.color }} />
                    <Typography variant="caption" sx={{ color: moverSummary.color, fontWeight: 700, fontSize: 10 }}>
                      {moverSummary.label}
                    </Typography>
                  </Box>
                )}
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
              startPublish={startPublish}
              status={status}
              onNavigate={navigate}
              mode={taskMode}
              setMode={changeTaskMode}
              automationStatus={automationStatus}
            />
          )}
          {activeTab === 'automation' && (
            <AutomationPanel
              status={automationStatus}
              refreshStatus={refreshAutomationStatus}
              webForm={form}
              onOpenTask={openTask}
              onNavigate={navigate}
              onDirtyChange={handleAutomationDirty}
            />
          )}
          {activeTab === 'design' && (
            <DesignPanel form={form} setForm={setForm} />
          )}
          {activeTab === 'logs' && (
            <TelemetryPanel
              logs={logs}
              status={status}
              task={task}
              onCancel={task?.kind === 'publish' ? cancelCurrentTask : undefined}
              onRetry={task?.kind === 'publish' ? retryCurrentTask : undefined}
            />
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
