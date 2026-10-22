# AgentCut 前端设计稿

Pencil 画布包含四张 1440 × 900 的桌面页面稿：

1. [上传项目](01-upload.png)：创建项目、整文件上传、已上传素材。
2. [AI 分析](02-analysis.png)：用户意图、任务进度、模拟/降级与质量评审标志。
3. [方案编辑](03-editor.png)：源视频、可视化时间线、片段操作与全局输出。
4. [预览导出](04-export.png)：成片预览、应用结果、输出路径与下载。

设计依据为 `AgentCut-front/src/App.tsx`、四个现有页面、`src/types/plan.ts`、`src/api/index.ts` 和 `src/components/AnalysisWarning.tsx`。页面中的项目名、视频信息、分数、任务 ID 和画面均为展示用示例数据。

实现时需注意：当前前端的编辑页主要是表单加 JSON 文本框，尚无视频预览和波形时间线；分析页轮询逻辑尚未把 `NEEDS_REVIEW` 作为终态处理。导出页的渲染动作应继续由用户明确触发。
