import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import Paper from '@mui/material/Paper';
import Button from '@mui/material/Button';
import Alert from '@mui/material/Alert';
import Snackbar from '@mui/material/Snackbar';
import Grid from '@mui/material/Grid';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';
import CircularProgress from '@mui/material/CircularProgress';

import RobotIcon from '@mui/icons-material/SmartToy';
import SaveIcon from '@mui/icons-material/Save';

import {
  automationApi, AutomationConfig, AutomationConfigResponse, AutomationEvent, AutomationStatus, errorMessage,
  FieldError, PublishJob, UploadRecord,
} from '../../../src/api';
import { syncServerTime } from '../../../src/automation';
import StatusCard from './StatusCard';
import AccountCard from './AccountCard';
import JobList from './JobList';
import ActivityFeed from './ActivityFeed';
import ChannelEditor from './ChannelEditor';
import RulesForm from './RulesForm';
import ProcessingForm from './ProcessingForm';
import UploadsTable from './UploadsTable';
import LogViewer from './LogViewer';

const TABS = [
  { key: 'overview', label: '概览' },
  { key: 'channels', label: '频道' },
  { key: 'rules', label: '扫描规则' },
  { key: 'processing', label: '处理与投稿' },
  { key: 'uploads', label: '投稿记录' },
  { key: 'logs', label: '日志' },
] as const;
type TabKey = (typeof TABS)[number]['key'];
const CONFIG_TABS: TabKey[] = ['channels', 'rules', 'processing'];
const TAB_KEY = 'automation-tab';

// 校验错误的字段路径 → 它在哪个标签页
const tabForError = (path: string): TabKey => {
  if (path.startsWith('channels')) return 'channels';
  if (path.startsWith('processing') || path.startsWith('upload')) return 'processing';
  return 'rules';
};

interface AutomationPanelProps {
  status: AutomationStatus | null;
  refreshStatus: () => void;
  webForm: Record<string, any>;
  onOpenTask: (taskId: string) => void;
  onNavigate: (tab: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}

const AutomationPanel = ({ status, refreshStatus, webForm, onOpenTask, onNavigate, onDirtyChange }: AutomationPanelProps) => {
  const [tab, setTab] = useState<TabKey>('overview');
  const [meta, setMeta] = useState<AutomationConfigResponse | null>(null);
  const [draft, setDraft] = useState<AutomationConfig | null>(null);
  const [baseline, setBaseline] = useState('');
  const [version, setVersion] = useState('');
  const [loadError, setLoadError] = useState('');
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState('');
  const [jobs, setJobs] = useState<PublishJob[]>([]);
  const [events, setEvents] = useState<AutomationEvent[]>([]);
  const [uploads, setUploads] = useState<UploadRecord[]>([]);
  const [uploadsLoading, setUploadsLoading] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [followLogs, setFollowLogs] = useState(true);

  const dirty = !!draft && JSON.stringify(draft) !== baseline;
  const errors = useMemo(() => Object.fromEntries(fieldErrors.map((e) => [e.path, e.message])), [fieldErrors]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  // 离开页面（关标签页、刷新）时提醒还没保存
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const loadConfig = useCallback(async () => {
    try {
      const res = await automationApi.getConfig();
      setMeta(res.data);
      setDraft(res.data.effective);
      setBaseline(JSON.stringify(res.data.effective));
      setVersion(res.data.version);
      setLoadError(res.data.error || '');
      setFieldErrors([]);
      setConflict(false);
    } catch (e) {
      setLoadError(errorMessage(e, '读取配置失败'));
    }
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const res = await automationApi.jobs(30);
      syncServerTime(res.data.server_time);
      setJobs(res.data.jobs);
    } catch {
      // 轮询失败下次再说
    }
  }, []);

  const loadEvents = useCallback(async () => {
    try {
      const res = await automationApi.events(200);
      setEvents(res.data.events);
    } catch {
      // 同上
    }
  }, []);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(TAB_KEY) as TabKey | null;
      if (saved && TABS.some((t) => t.key === saved)) setTab(saved);
    } catch {
      // 隐私模式读不了就用默认标签
    }
    loadConfig();
    loadJobs();
    loadEvents();
    const jobTimer = setInterval(loadJobs, 5000);
    const eventTimer = setInterval(loadEvents, 15000);
    return () => {
      clearInterval(jobTimer);
      clearInterval(eventTimer);
    };
  }, [loadConfig, loadJobs, loadEvents]);

  // 投稿记录和日志只在打开对应标签时拉
  useEffect(() => {
    if (tab !== 'uploads') return undefined;
    const load = async () => {
      setUploadsLoading(true);
      try {
        setUploads((await automationApi.uploads(2000)).data.uploads);
      } catch {
        // 下次再拉
      } finally {
        setUploadsLoading(false);
      }
    };
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [tab]);

  useEffect(() => {
    if (tab !== 'logs') return undefined;
    const load = async () => {
      try {
        setLogs((await automationApi.logs(800)).data.lines);
      } catch {
        // 下次再拉
      }
    };
    load();
    if (!followLogs) return undefined;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [tab, followLogs]);

  const changeTab = (next: TabKey) => {
    setTab(next);
    try {
      localStorage.setItem(TAB_KEY, next);
    } catch {
      // 记不住也没关系
    }
  };

  const updateDraft = (patch: (d: AutomationConfig) => AutomationConfig) => setDraft((d) => (d ? patch(d) : d));

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setFieldErrors([]);
    try {
      const res = await automationApi.saveConfig(draft, version);
      setDraft(res.data.effective);
      setBaseline(JSON.stringify(res.data.effective));
      setVersion(res.data.version);
      setConflict(false);
      setToast('已保存。投稿设置立即生效，其余从下一轮扫描开始生效');
      refreshStatus();
    } catch (e: any) {
      if (e?.response?.status === 422) {
        const list: FieldError[] = e.response.data.errors || [];
        setFieldErrors(list);
        if (list.length && !list.some((err) => tabForError(err.path) === tab)) changeTab(tabForError(list[0].path));
      } else if (e?.response?.status === 409) {
        setConflict(true);
      } else {
        setToast(`保存失败：${errorMessage(e)}`);
      }
    } finally {
      setSaving(false);
    }
  };

  const discard = () => {
    if (!confirm('放弃所有没保存的修改？')) return;
    loadConfig();
  };

  const togglePause = async () => {
    if (!status) return;
    setBusy(true);
    try {
      const res = await automationApi.pause(!status.paused);
      // 暂停只改了 paused 一个键：草稿跟着改，并换到新版本号，免得保存草稿时被当成冲突
      setVersion(res.data.version);
      setDraft((d) => (d ? { ...d, paused: res.data.paused } : d));
      setBaseline((b) => (b ? JSON.stringify({ ...JSON.parse(b), paused: res.data.paused }) : b));
      setToast(res.data.paused ? '已暂停自动扫描（Web 投稿照常处理）' : '已恢复自动扫描');
      refreshStatus();
    } catch (e) {
      setToast(`操作失败：${errorMessage(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const scanNow = async () => {
    setBusy(true);
    try {
      await automationApi.scan();
      setToast('已通知 mover，几秒内开始扫描');
      setTimeout(refreshStatus, 4000);
    } catch (e) {
      setToast(`操作失败：${errorMessage(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = async (job: PublishJob) => {
    if (!confirm('取消这个投稿任务？')) return;
    try {
      await automationApi.cancelJob(job.id);
      loadJobs();
    } catch (e) {
      setToast(errorMessage(e));
      loadJobs();
    }
  };

  const retryJob = async (job: PublishJob) => {
    try {
      const res = await automationApi.retryJob(job.id);
      loadJobs();
      onOpenTask(res.data.task_id);
    } catch (e) {
      setToast(errorMessage(e));
    }
  };

  const errorCount = (key: TabKey) => fieldErrors.filter((e) => tabForError(e.path) === key).length;
  const configTab = CONFIG_TABS.includes(tab);

  return (
    <Box sx={{ maxWidth: 1200, mx: 'auto', display: 'flex', flexDirection: 'column', gap: 3, pt: 2, pb: 6 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
        <RobotIcon sx={{ fontSize: 40, color: 'secondary.main' }} />
        <Box sx={{ flex: 1 }}>
          <Typography variant="h4" sx={{ fontWeight: 900, color: 'white' }}>自动搬运</Typography>
          <Typography variant="body2" color="text.secondary">
            定期扫描 YouTube 频道 → 生成双语视频 → 投稿 B 站。「制作任务」里选「生成并投稿」的链接也在这里排队处理。
          </Typography>
        </Box>
      </Box>

      <Tabs value={tab} onChange={(_, v) => changeTab(v)} variant="scrollable" scrollButtons="auto"
        sx={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        {TABS.map((t) => (
          <Tab key={t.key} value={t.key} sx={{ fontWeight: 700 }}
            label={errorCount(t.key) ? `${t.label}（${errorCount(t.key)} 处有误）` : t.label} />
        ))}
      </Tabs>

      {configTab && (
        <Paper elevation={0} sx={{
          position: 'sticky', top: 0, zIndex: 2, p: 1.5, px: 2, borderRadius: 2,
          bgcolor: dirty ? 'rgba(59,130,246,0.15)' : 'rgba(10,12,20,0.92)', backdropFilter: 'blur(12px)',
          border: '1px solid', borderColor: dirty ? 'rgba(59,130,246,0.4)' : 'rgba(255,255,255,0.05)',
          display: 'flex', alignItems: 'center', gap: 2,
        }}>
          <Typography variant="body2" sx={{ flex: 1, color: dirty ? 'primary.light' : 'text.secondary' }}>
            {dirty ? '有没保存的修改' : '配置已是最新。改完点保存，mover 下一轮扫描读到新配置（投稿设置立即生效）。'}
          </Typography>
          <Button size="small" disabled={!dirty || saving} onClick={discard} sx={{ px: 2, py: 0.75 }}>放弃</Button>
          <Button size="small" variant="contained" startIcon={saving ? <CircularProgress size={14} /> : <SaveIcon />}
            disabled={!dirty || saving} onClick={save} sx={{ px: 2, py: 0.75 }}>
            保存
          </Button>
        </Paper>
      )}

      {configTab && conflict && (
        <Alert severity="warning" action={<Button color="inherit" size="small" onClick={loadConfig}>重新加载</Button>}>
          config.json 在你打开页面之后被别处改过了（设置向导或手工编辑）。为了不覆盖那边的修改，这次没有保存：
          重新加载后再改一遍。
        </Alert>
      )}
      {configTab && fieldErrors.length > 0 && (
        <Alert severity="error">
          有 {fieldErrors.length} 处不合法，没有保存：
          {fieldErrors.slice(0, 5).map((e) => `${e.path} ${e.message}`).join('；')}
        </Alert>
      )}
      {configTab && loadError && <Alert severity="error">{loadError}</Alert>}
      {configTab && !draft && !loadError && <CircularProgress />}

      {tab === 'overview' && (
        <Grid container spacing={3}>
          <Grid size={12}>
            <StatusCard status={status} busy={busy} onScan={scanNow} onTogglePause={togglePause} />
          </Grid>
          <Grid size={{ xs: 12, md: 7 }}>
            <JobList
              jobs={jobs}
              onOpen={(job) => onOpenTask(job.id)}
              onCancel={cancelJob}
              onRetry={retryJob}
              onNewJob={() => onNavigate('task')}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 5 }}>
            <AccountCard />
          </Grid>
          <Grid size={12}>
            <ActivityFeed events={events} />
          </Grid>
        </Grid>
      )}

      {tab === 'channels' && draft && meta && (
        <ChannelEditor
          channels={draft.channels || []}
          defaults={meta.channel_defaults}
          errors={errors}
          onChange={(channels) => updateDraft((d) => ({ ...d, channels }))}
        />
      )}
      {tab === 'rules' && draft && <RulesForm draft={draft} errors={errors} onChange={updateDraft} />}
      {tab === 'processing' && draft && meta && (
        <ProcessingForm draft={draft} meta={meta} errors={errors} webForm={webForm} onChange={updateDraft} />
      )}

      {tab === 'uploads' && <UploadsTable uploads={uploads} loading={uploadsLoading} />}

      {tab === 'logs' && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
              mover 的输出（最近 800 行，userdata/runtime/mover.log）。更早的用 docker compose logs mover。
            </Typography>
            <FormControlLabel
              control={<Switch size="small" checked={followLogs} onChange={(e) => setFollowLogs(e.target.checked)} />}
              label="自动刷新"
            />
          </Box>
          <LogViewer lines={logs} height="calc(100vh - 300px)"
            emptyText="还没有日志：mover 升级到这个版本、启动之后才会写 runtime/mover.log" />
        </Box>
      )}

      <Snackbar open={!!toast} autoHideDuration={4000} onClose={() => setToast('')} message={toast}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }} />
    </Box>
  );
};

export default AutomationPanel;
