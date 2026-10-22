interface RequestFailure {
  code?: string;
  message?: string;
  response?: { status?: number; data?: { message?: unknown; detail?: unknown; error?: unknown } };
}

export function apiErrorMessage(error: RequestFailure): string {
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') return '请求超时，请稍后重试。';
  if (error.code === 'ERR_NETWORK') return '无法连接后端，请确认服务已启动后重试。';
  const supplied = error.response?.data?.message ?? error.response?.data?.detail;
  if (typeof supplied === 'string' && supplied.trim()) return supplied;
  const status = error.response?.status;
  if (status && status >= 500) return `后端服务处理失败（HTTP ${status}），请稍后重试。`;
  if (status === 404) return '请求的数据不存在（HTTP 404）。';
  const description = error.response?.data?.error;
  return typeof description === 'string' && description.trim() ? description : error.message || '网络请求失败，请重试。';
}
