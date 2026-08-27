import axios from 'axios';

/**
 * axios 实例：AgentCut 后端 REST API（v1）
 * baseURL 对齐后端 Controller 前缀 /api/v1
 */
const client = axios.create({
  baseURL: 'http://localhost:8080/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// 响应拦截器：仅统一错误出口，不拆包（后端各接口直接返回业务对象）
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error?.response?.data?.message ?? error?.response?.data?.error ?? error?.message ?? '网络请求失败';
    console.error('[AgentCut] 请求失败:', message);
    return Promise.reject(error);
  },
);

export default client;
