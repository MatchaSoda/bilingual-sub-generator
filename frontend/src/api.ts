import axios, { AxiosResponse } from 'axios';

// 相对路径模式：由后端统一托管静态文件和 API
const baseURL = '/api';

const api = axios.create({
  baseURL: baseURL,
  timeout: 10000,
});

export interface TaskCreateData {
  url: string;
  model: string;
  translation_model: string;
  [key: string]: any;
}

export const taskApi = {
  create: (data: TaskCreateData): Promise<AxiosResponse<any>> => api.post('/tasks', data),
  getStatus: (taskId: string): Promise<AxiosResponse<any>> => api.get(`/status/${taskId}`),
};

// web = Web 界面做的成品（data/downloads），auto = 自动搬运的成品（userdata/data），见 backend/utils/library.py
export type LibrarySource = 'web' | 'auto';

export interface LibraryItem {
  name: string;
  source: LibrarySource;
  path: string;
  thumbnail: string;
  size: string;
  size_bytes: number;
  time: string;
  mtime: number;
}

export const libraryApi = {
  list: (): Promise<AxiosResponse<LibraryItem[]>> => api.get('/library'),
  delete: (name: string, source: LibrarySource): Promise<AxiosResponse<any>> =>
    api.delete(`/library/${encodeURIComponent(name)}`, { params: { source } }),
  getDownloadUrl: (path: string): string => `${baseURL}${path}`,
};

export const configApi = {
  get: (): Promise<AxiosResponse<any>> => api.get('/config'),
  save: (keys: string): Promise<AxiosResponse<any>> => api.post('/config', { google_api_keys: keys }),
};

export default api;

// ---------------------------------------------------------------- 自动搬运（backend/api/automation_routes.py）
// Web 不直接投稿：任务写进 userdata/jobs/，由 mover 按顺序执行，和频道扫描排同一条队列。

export type PublishJobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

export interface PublishJob {
  id: string;
  kind: 'publish';
  status: PublishJobStatus;
  stage: string;
  url: string;
  video_id: string;
  title: string | null;
  options: { channel?: number | null; tid?: number | null; tags?: string | null; title?: string | null; retry_of?: string };
  origin: string;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  result: { bvid: string | null; title: string; bili_title: string; output: string | null } | null;
  error: string | null;
  failed_stage?: string;
  queue_position?: number | null;
}

export interface MoverCurrent {
  kind: 'scan' | 'auto' | 'manual';
  channel?: string;
  video_id?: string;
  title?: string | null;
  job_id?: string;
  stage?: string;
  started_at?: number;
}

export interface CycleSummary {
  channels: number;
  found: number;
  new: number;
  matched: number;
  uploaded: number;
  failed: number;
  skipped: Record<string, number>;
  started_at: number;
  finished_at: number;
  forced: boolean;
}

export interface MoverStatus {
  online: boolean;
  heartbeat_at: number | null;
  heartbeat_age: number | null;
  phase?: 'starting' | 'cycle' | 'scanning' | 'processing' | 'idle';
  current?: MoverCurrent | null;
  next_scan_at?: number | null;
  last_cycle?: CycleSummary | null;
  paused?: boolean;
  interval?: number;
  started_at?: number;
}

export interface EventSummary {
  uploaded: number;
  failed: number;
  matched: number;
  cycles: number;
  skipped: Record<string, number>;
}

export interface AutomationStatus {
  server_time: number;
  mover: MoverStatus;
  automation_enabled: boolean | null;
  config_exists: boolean;
  config_error: string | null;
  paused: boolean;
  channels: number;
  check_interval_seconds: number;
  queue: { queued: number; running: PublishJob | null };
  stats_24h: EventSummary;
}

export interface ChannelConfig {
  name: string;
  url: string;
  keyword: string;
  exclude: string[];
  bili_tid: number;
  tags: string;
  [key: string]: any;
}

export interface AutomationConfig {
  channels: ChannelConfig[];
  paused: boolean;
  check_interval_seconds: number;
  playlist_items: number;
  description_fetch_interval_seconds: number;
  max_uploads_per_cycle: number;
  backfill: { mode: 'all' | 'since_first_start'; lookback_hours: number };
  processing: {
    whisper_model: string;
    segment_mode: string;
    gemini_model: string;
    translation_batch_size: number;
    enable_furigana: boolean;
    translate_title: boolean;
    fix_source_text: boolean;
    style: Record<string, number>;
  };
  upload: {
    line: string | null;
    retries: number;
    retry_delay_seconds: number;
    title_template: string;
    description_template: string;
  };
  cleanup: { keep_days: number };
  [key: string]: any;
}

export interface AutomationConfigResponse {
  exists: boolean;
  error: string | null;
  version: string;
  config: Partial<AutomationConfig>;
  effective: AutomationConfig;
  channel_defaults: ChannelConfig;
  style_defaults: Record<string, number>;
  style_fields: Record<string, { type: 'int' | 'float'; min: number; max: number }>;
  options: {
    whisper_models: string[];
    gemini_models: string[];
    segment_modes: string[];
    backfill_modes: string[];
    upload_lines: string[];
  };
}

export interface FieldError {
  path: string;
  message: string;
}

export interface AutomationEvent {
  ts: number;
  type: 'skip' | 'match' | 'uploaded' | 'failed' | 'cycle' | 'cleanup' | string;
  [key: string]: any;
}

export interface UploadRecord {
  video_id: string;
  url: string;
  title: string;
  original_title?: string;
  bili_title?: string;
  bvid: string | null;
  tid?: number;
  output?: string;
  source?: string;
  origin?: string;
  channel?: string;
  job_id?: string | null;
  uploaded_at: number;
}

export interface AccountStatus {
  exists: boolean;
  logged_in: boolean;
  mid?: string | null;
  expires_at?: number | null;
  updated_at?: number;
  platform?: string;
  valid?: boolean | null;
  uname?: string | null;
  checked_at?: number;
  error?: string;
}

export interface QrSession {
  id: string;
  url: string;
  state: 'waiting' | 'success' | 'failed' | 'expired' | 'cancelled';
  created_at: number;
  expires_at: number;
  message: string | null;
  mid?: string;
}

export interface PublishRequest {
  url: string;
  channel?: number | null;
  tid?: number | null;
  tags?: string | null;
  title?: string | null;
  force?: boolean;
}

export const automationApi = {
  status: (): Promise<AxiosResponse<AutomationStatus>> => api.get('/automation/status'),
  scan: (): Promise<AxiosResponse<any>> => api.post('/automation/scan'),
  pause: (paused: boolean): Promise<AxiosResponse<{ paused: boolean; version: string }>> =>
    api.post('/automation/pause', { paused }),
  getConfig: (): Promise<AxiosResponse<AutomationConfigResponse>> => api.get('/automation/config'),
  saveConfig: (config: AutomationConfig, version: string): Promise<AxiosResponse<any>> =>
    api.put('/automation/config', { config, version }),
  saveStyle: (style: Record<string, number> | null): Promise<AxiosResponse<any>> =>
    api.put('/automation/style', { style }),
  events: (limit = 100): Promise<AxiosResponse<{ server_time: number; events: AutomationEvent[] }>> =>
    api.get('/automation/events', { params: { limit } }),
  uploads: (limit = 200): Promise<AxiosResponse<{ uploads: UploadRecord[] }>> =>
    api.get('/automation/uploads', { params: { limit } }),
  logs: (lines = 300): Promise<AxiosResponse<{ exists: boolean; lines: string[] }>> =>
    api.get('/automation/logs', { params: { lines } }),
  createJob: (request: PublishRequest): Promise<AxiosResponse<{ task_id: string; job: PublishJob; duplicate?: boolean }>> =>
    api.post('/automation/jobs', request),
  jobs: (limit = 50): Promise<AxiosResponse<{ server_time: number; jobs: PublishJob[] }>> =>
    api.get('/automation/jobs', { params: { limit } }),
  cancelJob: (id: string): Promise<AxiosResponse<any>> => api.post(`/automation/jobs/${id}/cancel`),
  retryJob: (id: string): Promise<AxiosResponse<{ task_id: string; job: PublishJob }>> =>
    api.post(`/automation/jobs/${id}/retry`),
  account: (check = true): Promise<AxiosResponse<AccountStatus>> =>
    api.get('/automation/account', { params: { check } }),
  startQrLogin: (): Promise<AxiosResponse<QrSession>> => api.post('/automation/account/qrcode'),
  qrLoginStatus: (id: string): Promise<AxiosResponse<QrSession>> => api.get(`/automation/account/qrcode/${id}`),
  cancelQrLogin: (id: string): Promise<AxiosResponse<any>> => api.delete(`/automation/account/qrcode/${id}`),
};

// 接口报错时给人看的那句话（FastAPI 的 detail，或者网络错误）
export const errorMessage = (error: any, fallback = '请求失败'): string => {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || String(d)).join('；');
  if (error?.code === 'ECONNABORTED') return '请求超时';
  return error?.message || fallback;
};
