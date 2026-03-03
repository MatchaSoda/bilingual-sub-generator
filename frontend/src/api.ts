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

export const libraryApi = {
  list: (): Promise<AxiosResponse<any[]>> => api.get('/library'),
  delete: (name: string): Promise<AxiosResponse<any>> => api.delete(`/library/${name}`),
  clear: (): Promise<AxiosResponse<any>> => api.delete('/library'),
  getDownloadUrl: (path: string): string => `${baseURL}${path}`,
};

export const configApi = {
  get: (): Promise<AxiosResponse<any>> => api.get('/config'),
  save: (keys: string): Promise<AxiosResponse<any>> => api.post('/config', { google_api_keys: keys }),
};

export default api;
