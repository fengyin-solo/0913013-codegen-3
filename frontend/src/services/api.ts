import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export const authAPI = {
  login: (username: string, password: string) =>
    api.post('/auth/login', new URLSearchParams({ username, password }), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    }),
  register: (data: any) => api.post('/auth/register', data),
  getCurrentUser: () => api.get('/auth/me'),
  updateCurrentUser: (data: any) => api.put('/auth/me', data),
  listUsers: () => api.get('/auth/users'),
};

export const projectsAPI = {
  list: () => api.get('/projects'),
  create: (data: any) => api.post('/projects', data),
  get: (id: number) => api.get(`/projects/${id}`),
  update: (id: number, data: any) => api.put(`/projects/${id}`, data),
  delete: (id: number) => api.delete(`/projects/${id}`),
  listMembers: (id: number) => api.get(`/projects/${id}/members`),
  addMember: (id: number, data: any) => api.post(`/projects/${id}/members`, data),
  updateMember: (projectId: number, memberId: number, data: any) =>
    api.put(`/projects/${projectId}/members/${memberId}`, data),
  removeMember: (projectId: number, memberId: number) =>
    api.delete(`/projects/${projectId}/members/${memberId}`),
  // 批量处理
  batchPreflight: (data: {
    action: 'assign_members' | 'transfer_data';
    project_ids: number[];
    target_project_id?: number;
    user_id?: number;
    role?: string;
  }) => api.post('/projects/batch/preflight', data),
  batchAssignMembers: (projectIds: number[], userId: number, role: string) =>
    api.post('/projects/batch/assign-members', {
      project_ids: projectIds,
      user_id: userId,
      role,
    }),
  batchTransferData: (projectIds: number[], targetProjectId: number) =>
    api.post('/projects/batch/transfer-data', {
      project_ids: projectIds,
      target_project_id: targetProjectId,
    }),
  batchRetryTransfer: (seismicDataIds: number[], targetProjectId: number) =>
    api.post('/projects/batch/retry-transfer', {
      seismic_data_ids: seismicDataIds,
      target_project_id: targetProjectId,
    }),
};

export const seismicAPI = {
  list: (projectId: number) => api.get(`/seismic/project/${projectId}`),
  upload: (projectId: number, name: string, description: string, file: File, onProgress?: (progress: number) => void) => {
    const formData = new FormData();
    formData.append('name', name);
    if (description) formData.append('description', description);
    formData.append('file', file);

    return api.post(`/seismic/project/${projectId}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(progress);
        }
      },
    });
  },
  get: (id: number) => api.get(`/seismic/${id}`),
  delete: (id: number) => api.delete(`/seismic/${id}`),
  getSlice: (seismicId: number, sliceType: string, sliceIndex: number, params?: any) =>
    api.get(`/seismic/${seismicId}/slice/${sliceType}/${sliceIndex}`, {
      params: { format: 'json', ...params },
    }),
  getSliceImage: (seismicId: number, sliceType: string, sliceIndex: number, params?: any) =>
    api.get(`/seismic/${seismicId}/slice/${sliceType}/${sliceIndex}`, {
      params: { format: 'png', ...params },
      responseType: 'blob',
    }),
  getSubvolume: (seismicId: number, params: any) =>
    api.post(`/seismic/${seismicId}/subvolume`, null, { params }),
  measure: (data: any) => api.post('/seismic/measurement', data),
};

export const annotationsAPI = {
  list: (seismicId: number) => api.get(`/annotations/seismic/${seismicId}`),
  create: (data: any) => api.post('/annotations', data),
  get: (id: number) => api.get(`/annotations/${id}`),
  update: (id: number, data: any) => api.put(`/annotations/${id}`, data),
  delete: (id: number) => api.delete(`/annotations/${id}`),
};

export const wellsAPI = {
  list: (projectId: number) => api.get(`/wells/project/${projectId}`),
  create: (data: any) => api.post('/wells', data),
  get: (id: number) => api.get(`/wells/${id}`),
  update: (id: number, data: any) => api.put(`/wells/${id}`, data),
  delete: (id: number) => api.delete(`/wells/${id}`),
};

export default api;
