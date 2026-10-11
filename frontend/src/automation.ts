// 自动搬运相关的显示文字和时间格式，几个面板共用。

import type { SubtitleStyle } from './api';

// 和 backend/utils/pipeline_stages.py 的 STAGES 对应；proofread 只有开了「AI 原文纠错」才有，upload 只有投稿任务才有
export const PIPELINE_STAGES: { key: string; label: string }[] = [
  { key: 'download', label: '下载' },
  { key: 'transcribe', label: '转写' },
  { key: 'proofread', label: '纠错' },
  { key: 'translate', label: '翻译' },
  { key: 'encode', label: '压制' },
  { key: 'upload', label: '投稿' },
];

export const STAGE_LABELS: Record<string, string> = {
  queued: '排队中',
  download: '下载',
  transcribe: '转写',
  proofread: '纠错',
  translate: '翻译',
  encode: '压制',
  upload: '投稿',
  description: '拉简介',
  prepare: '准备',
  cli: '生成',
  output: '生成',
  done: '完成',
  failed: '失败',
  cancelled: '已取消',
};

export const PHASE_LABELS: Record<string, string> = {
  starting: '启动中',
  cycle: '准备本轮',
  scanning: '扫描频道',
  processing: '处理视频',
  idle: '休眠',
};

export const SKIP_REASON_LABELS: Record<string, string> = {
  keyword: '关键词不匹配',
  exclude: '命中排除词',
  cutoff: '早于起点',
  description_failed: '拉简介失败',
};

export const ORIGIN_LABELS: Record<string, string> = {
  auto: '自动搬运',
  manual: 'Web 投稿',
  backfill: '补投脚本',
};

export const JOB_STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '进行中',
  done: '已投稿',
  failed: '失败',
  cancelled: '已取消',
};

// 「系统设置」和「自动搬运」两个设置页共用。10-11 同一条新闻实测（容器 CPU）：large-v3 217 秒、turbo 82 秒，
// large-v3 还认出了 turbo 整段漏掉的一段；两个都常常不出标点，所以这里不拿标点比（RUNBOOK §5.14）
export const WHISPER_LABELS: Record<string, string> = {
  'large-v3-turbo': 'Large-V3-Turbo（默认，速度快）',
  'large-v3': 'Large-V3（最准，比 Turbo 慢 2～3 倍）',
  medium: 'Medium',
  small: 'Small（快，错得多）',
  base: 'Base',
  tiny: 'Tiny（最快，错得最多）',
};

// 「自动搬运」页记住上次打开的子页面；别的页面要直接跳到某个子页面就先写这里
export const AUTOMATION_TAB_KEY = 'automation-tab';
export const rememberAutomationTab = (tab: string) => {
  try {
    localStorage.setItem(AUTOMATION_TAB_KEY, tab);
  } catch {
    // 隐私模式写不了，就停在上次的子页面
  }
};

export const AI_CORRECTION_DESCRIPTION =
  '翻译前单独校一遍全片：对照标题和简介改语音识别的错字。读音对不上的不改，标题、简介里出现的写法放宽要求';

export const bilibiliVideoUrl = (bvid: string) => `https://www.bilibili.com/video/${bvid}`;
export const youtubeVideoUrl = (videoId: string) => `https://www.youtube.com/watch?v=${videoId}`;

// 浏览器和服务器的时钟可能差几秒（换台电脑看页面），所有相对时间都按服务器时间算
let serverOffsetMs = 0;
export const syncServerTime = (serverTime?: number) => {
  if (serverTime) serverOffsetMs = serverTime * 1000 - Date.now();
};
export const serverNow = () => (Date.now() + serverOffsetMs) / 1000;

export const formatDuration = (seconds: number): string => {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} 秒`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分钟`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (h < 24) return rest ? `${h} 小时 ${rest} 分` : `${h} 小时`;
  return `${Math.floor(h / 24)} 天`;
};

export const formatRelative = (ts?: number | null): string => {
  if (!ts) return '—';
  const diff = ts - serverNow();
  if (Math.abs(diff) < 10) return '刚刚';
  return diff > 0 ? `${formatDuration(diff)}后` : `${formatDuration(-diff)}前`;
};

export const formatClock = (ts?: number | null, withDate = true): string => {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (!withDate) return time;
  const date = `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  // 不是今年的日期带上年份（B 站登录的到期日经常在明年）
  return d.getFullYear() === new Date(serverNow() * 1000).getFullYear() ? `${date} ${time}` : `${d.getFullYear()}-${date} ${time}`;
};

export const formatBytes = (bytes: number): string => {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.round(bytes / 1e3)} KB`;
};

// 卡片的统一外观（和其他面板一致）
export const cardSx = {
  p: 3,
  borderRadius: 2,
  bgcolor: 'rgba(255, 255, 255, 0.03)',
  border: '1px solid rgba(255, 255, 255, 0.05)',
};

export const filledFieldSx = {
  '& .MuiFilledInput-root': {
    borderRadius: 1.5,
    bgcolor: 'rgba(0,0,0,0.3)',
    '&:hover': { bgcolor: 'rgba(0,0,0,0.4)' },
  },
};

// 视觉实验室表单里属于字幕样式的字段（和 backend/utils/automation_store.py 的 STYLE_FIELDS 一致）
export const STYLE_NUMBER_KEYS = [
  'font_size_main', 'main_bottom', 'font_alpha', 'outline_alpha', 'font_weight', 'outline_main', 'shadow_main',
  'font_size_sub', 'sub_bottom', 'sub_alpha', 'outline_sub_alpha', 'font_weight_sub', 'outline_sub', 'shadow_sub',
];
// 字体（fontconfig 的字族名）和颜色（#RRGGBB），对应 STYLE_FONT_FIELDS / STYLE_COLOR_FIELDS。main 是日文原文，sub 是中文译文
export const STYLE_TEXT_KEYS = ['font_main', 'font_sub', 'color_main', 'outline_color_main', 'color_sub', 'outline_color_sub'];
export const STYLE_KEYS = [...STYLE_NUMBER_KEYS, ...STYLE_TEXT_KEYS];

export const pickStyle = (form: Record<string, any>): SubtitleStyle => {
  const style: SubtitleStyle = {};
  STYLE_NUMBER_KEYS.forEach((key) => {
    const value = Number(form[key]);
    if (form[key] !== undefined && form[key] !== '' && Number.isFinite(value)) style[key] = value;
  });
  STYLE_TEXT_KEYS.forEach((key) => {
    if (typeof form[key] === 'string' && form[key].trim()) style[key] = form[key].trim();
  });
  return style;
};

// 数字按数值比（90 和 90.0 一样），字体和颜色按文字比，颜色不分大小写
export const sameStyleValue = (key: string, a: unknown, b: unknown): boolean =>
  STYLE_TEXT_KEYS.includes(key)
    ? String(a ?? '').toUpperCase() === String(b ?? '').toUpperCase()
    : Number(a) === Number(b);

export const sameStyle = (a: SubtitleStyle, b: SubtitleStyle): boolean =>
  STYLE_KEYS.every((key) => sameStyleValue(key, a[key], b[key]));
