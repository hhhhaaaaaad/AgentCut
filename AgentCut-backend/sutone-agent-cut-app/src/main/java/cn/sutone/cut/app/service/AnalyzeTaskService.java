package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.adapter.port.IVideoAnalysisClient;
import cn.sutone.cut.domain.analysis.adapter.repository.IAnalysisReportRepository;
import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import cn.sutone.cut.domain.asset.adapter.repository.IAssetRepository;
import cn.sutone.cut.domain.asset.model.entity.AssetEntity;
import cn.sutone.cut.domain.asset.model.valobj.enums.AssetType;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.service.PlanDomainService;
import cn.sutone.cut.domain.project.model.entity.ProjectEntity;
import cn.sutone.cut.domain.project.service.ProjectDomainService;
import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskType;
import cn.sutone.cut.domain.task.service.TaskDomainService;
import cn.sutone.cut.infrastructure.plan.PlanJsonMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 分析任务编排：建任务 → 调 Python → 回调落库。
 */
@Slf4j
@Service
public class AnalyzeTaskService {

    private final ProjectDomainService projectDomainService;
    private final IAssetRepository assetRepository;
    private final ITaskRepository taskRepository;
    private final TaskDomainService taskDomainService;
    private final IVideoAnalysisClient videoAnalysisClient;
    private final IAnalysisReportRepository analysisReportRepository;
    private final PlanJsonMapper planJsonMapper;
    private final PlanDomainService planDomainService;

    @Value("${agentcut.callback.base-url:http://127.0.0.1:8080}")
    private String callbackBaseUrl;

    public AnalyzeTaskService(ProjectDomainService projectDomainService, IAssetRepository assetRepository,
                              ITaskRepository taskRepository, TaskDomainService taskDomainService,
                              IVideoAnalysisClient videoAnalysisClient,
                              IAnalysisReportRepository analysisReportRepository,
                              PlanJsonMapper planJsonMapper, PlanDomainService planDomainService) {
        this.projectDomainService = projectDomainService;
        this.assetRepository = assetRepository;
        this.taskRepository = taskRepository;
        this.taskDomainService = taskDomainService;
        this.videoAnalysisClient = videoAnalysisClient;
        this.analysisReportRepository = analysisReportRepository;
        this.planJsonMapper = planJsonMapper;
        this.planDomainService = planDomainService;
    }

    /**
     * 发起视频分析，返回任务 ID。
     */
    public Long analyze(Long projectId, String targetJson) {
        ProjectEntity project = projectDomainService.query(projectId);
        if (project == null) {
            throw new IllegalArgumentException("项目不存在: " + projectId);
        }
        AssetEntity source = assetRepository.queryByProjectId(projectId).stream()
                .filter(a -> a.getType() == AssetType.SOURCE)
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("项目无源视频素材"));

        // 用 Jackson 序列化 payload（手动拼 JSON 会导致 Windows 路径反斜杠转义错误）
        java.util.Map<String, Object> payload = new java.util.HashMap<>();
        payload.put("videoUrl", source.getOssUrl());
        TaskEntity task = taskDomainService.createPending(projectId, TaskType.ANALYZE,
                planJsonMapper.writeJson(payload));

        String callbackUrl = callbackBaseUrl + "/api/v1/analyze/callback?taskId=" + task.getTaskId();
        log.info("analyze 触发: taskId={}, callbackUrl={}", task.getTaskId(), callbackUrl);
        String pyResp = videoAnalysisClient.submitAnalyze(source.getOssUrl(), callbackUrl, targetJson);
        log.info("analyze Python 响应: {}", pyResp);

        return task.getTaskId();
    }

    /**
     * Python 分析完成回调：保存报告 + 反序列化/校验/保存方案，标记任务成功。
     */
    public void handleCallback(Long taskId, String reportJson, String planJson) {
        TaskEntity task = taskRepository.queryById(taskId);
        if (task == null) {
            throw new IllegalArgumentException("任务不存在: " + taskId);
        }

        AnalysisReportEntity report = AnalysisReportEntity.builder()
                .projectId(task.getProjectId())
                .version(1)
                .contentJson(reportJson)
                .status("SUCCESS")
                .build();
        analysisReportRepository.save(report);

        try {
            PlanEntity plan = planJsonMapper.fromJson(planJson);
            plan.setProjectId(String.valueOf(task.getProjectId()));
            // 回填源视频 URL：模拟模式下方案 source.url 可能为空，用源素材 URL 覆盖
            fillSourceUrl(plan, task.getProjectId());
            // 反序列化后重新规范化序列化，作为版本存档内容
            String canonicalJson = planJsonMapper.toJson(plan);
            planDomainService.savePlan(plan, canonicalJson);
        } catch (Exception e) {
            taskDomainService.markFailed(taskId, "方案反序列化失败: " + e.getMessage());
            return;
        }

        taskDomainService.markSuccess(taskId, planJson);
    }

    /**
     * 回填源视频 URL：方案 source.url 为空时，用项目源素材的 ossUrl 覆盖。
     */
    private void fillSourceUrl(PlanEntity plan, Long projectId) {
        if (plan.getSource() == null) {
            return;
        }
        if (plan.getSource().getUrl() != null && !plan.getSource().getUrl().isBlank()) {
            return;
        }
        assetRepository.queryByProjectId(projectId).stream()
                .filter(a -> a.getType() == AssetType.SOURCE)
                .findFirst()
                .ifPresent(a -> plan.getSource().setUrl(a.getOssUrl()));
    }
}
