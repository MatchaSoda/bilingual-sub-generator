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
