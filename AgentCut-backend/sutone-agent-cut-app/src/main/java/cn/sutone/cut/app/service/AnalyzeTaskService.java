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
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 分析任务编排：建任务 → 调 Python → 回调落库。
 */
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

    @Value("${agentcut.callback.base-url:http://localhost:8080}")
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

        TaskEntity task = taskDomainService.createPending(projectId, TaskType.ANALYZE,
                "{\"videoUrl\":\"" + source.getOssUrl() + "\"}");

        String callbackUrl = callbackBaseUrl + "/api/v1/analyze/callback?taskId=" + task.getTaskId();
        videoAnalysisClient.submitAnalyze(source.getOssUrl(), callbackUrl, targetJson);

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
            plan.setProjectId(task.getProjectId());
            planDomainService.savePlan(plan);
        } catch (Exception e) {
            taskDomainService.markFailed(taskId, "方案反序列化失败: " + e.getMessage());
            return;
        }

        taskDomainService.markSuccess(taskId, planJson);
    }
}
