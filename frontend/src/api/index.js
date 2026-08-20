import request from './request'

export const authApi = {
  login: (data) => request.post('/auth/login', data),
  info: () => request.get('/auth/info'),
}

export const modelApi = {
  list: (params) => request.get('/models', { params }),
  add: (data) => request.post('/models', data),
  update: (id, data) => request.put(`/models/${id}`, data),
  remove: (id) => request.delete(`/models/${id}`),
  upload: (id, form) => request.post(`/models/${id}/upload`, form, { timeout: 0 }),
  registerBuiltin: (data) => request.post('/models/register-builtin', data, { timeout: 0 }),
  builtins: () => request.get('/models/builtins'),
  downloadWeight: (id) => request.post(`/models/${id}/download-weight`, null, { timeout: 0 }),
  downloadProgress: (jobId) => request.get(`/models/download-progress/${jobId}`, { timeout: 0 }),
}

export const detectApi = {
  image: (id, form) => request.post(`/detect/${id}/image`, form, { timeout: 0 }),
  video: (id, form) => request.post(`/detect/${id}/video`, form, { timeout: 0 }),
  progress: (id, jobId) => request.get(`/detect/${id}/video-progress/${jobId}`, { timeout: 0 }),
  output: (name) => request.get(`/detect/output/${name}`, { responseType: 'blob', timeout: 0 }),
}

export const datasetApi = {
  list: () => request.get('/datasets'),
  add: (data) => request.post('/datasets', data),
  update: (id, data) => request.put(`/datasets/${id}`, data),
  remove: (id) => request.delete(`/datasets/${id}`),
  upload: (id, form) => request.post(`/datasets/${id}/upload`, form, { timeout: 0 }),
  extract: (id, form) => request.post(`/datasets/${id}/extract-frames`, form, { timeout: 0 }),
  samples: (id) => request.get(`/datasets/${id}/samples`),
  imageUrl: (id, stem) => `/api/datasets/${id}/image/${encodeURIComponent(stem)}`,
  labels: (id, stem) => request.get(`/datasets/${id}/boxes`, { params: { stem } }),
  saveLabels: (id, data) => request.put(`/datasets/${id}/boxes`, data),
  build: (id) => request.post(`/datasets/${id}/build`, null, { timeout: 0 }),
  prelabel: (id, data) => request.post(`/datasets/${id}/annotate/prelabel`, data, { timeout: 0 }),
  sam: (id, data) => request.post(`/datasets/${id}/annotate/sam`, data, { timeout: 0 }),
  importNdjson: (form) => request.post('/datasets/import-ndjson', form, { timeout: 0 }),
  importProgress: (jobId) => request.get(`/datasets/import-progress/${jobId}`, { timeout: 0 }),
  retryImport: (id, form) => request.post(`/datasets/${id}/retry-import`, form || {}, { timeout: 0 }),
  pauseImport: (id) => request.post(`/datasets/${id}/import-pause`),
  resumeImport: (id) => request.post(`/datasets/${id}/import-resume`),
  openFolder: (id) => request.post(`/datasets/${id}/open-folder`),
  colors: (id) => request.get(`/datasets/${id}/colors`),
  saveColors: (id, data) => request.put(`/datasets/${id}/colors`, data),
  classColors: () => request.get('/datasets/class-colors'),
}

export const jobApi = {
  list: () => request.get('/jobs'),
  add: (data) => request.post('/jobs', data),
  start: (id) => request.post(`/jobs/${id}/start`),
  get: (id) => request.get(`/jobs/${id}`),
  remove: (id) => request.delete(`/jobs/${id}`),
  baseModels: () => request.get('/jobs/base-models'),
  limits: () => request.get('/jobs/limits'),
  plotFile: (id, name) => request.get(`/jobs/${id}/plots/${encodeURIComponent(name)}`, { responseType: 'blob' }),
}
