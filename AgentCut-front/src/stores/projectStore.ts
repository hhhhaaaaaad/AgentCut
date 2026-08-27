import { create } from 'zustand';
import type { Plan } from '../types/plan';
import type { Project, Task } from '../api';

/**
 * 全局项目状态：当前项目 / 分析任务 / 剪辑方案 / 版本列表。
 * 各页面通过此 store 共享数据，避免层层传参。
 */
interface ProjectState {
  project: Project | null;
  task: Task | null;
  plan: Plan | null;
  planVersions: string[];

  setProject: (project: Project | null) => void;
  setTask: (task: Task | null) => void;
  setPlan: (plan: Plan | null) => void;
  setPlanVersions: (versions: string[]) => void;
  /** 清空全部（如新建项目前） */
  reset: () => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  project: null,
  task: null,
  plan: null,
  planVersions: [],

  setProject: (project) => set({ project }),
  setTask: (task) => set({ task }),
  setPlan: (plan) => set({ plan }),
  setPlanVersions: (planVersions) => set({ planVersions }),
  reset: () => set({ project: null, task: null, plan: null, planVersions: [] }),
}));
