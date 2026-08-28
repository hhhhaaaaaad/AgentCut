package cn.sutone.cut.app.service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import cn.sutone.cut.domain.plan.adapter.repository.IPlanRepository;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.render.adapter.port.IRenderEngine;
import cn.sutone.cut.domain.render.model.valobj.RenderCommand;
import cn.sutone.cut.domain.render.model.valobj.RenderOutput;
import cn.sutone.cut.domain.render.service.RenderPlanService;
import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskType;
import cn.sutone.cut.domain.task.service.TaskDomainService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 渲染任务编排：建 RENDER 任务 → 读方案 → 编译 → FFmpeg 渲染 → 成片 → 标记成功。
 */
@Service
public class RenderTaskService {

    private final IPlanRepository planRepository;
    private final RenderPlanService renderPlanService;
    private final IRenderEngine renderEngine;
    private final TaskDomainService taskDomainService;
    private final ObjectMapper objectMapper;

    @Value("${agentcut.render.work-dir:./data/work}")
    private String workDir;

    public RenderTaskService(IPlanRepository planRepository, RenderPlanService renderPlanService,
                             IRenderEngine renderEngine, TaskDomainService taskDomainService,
                             ObjectMapper objectMapper) {
        this.planRepository = planRepository;
        this.renderPlanService = renderPlanService;
        this.renderEngine = renderEngine;
        this.taskDomainService = taskDomainService;
        this.objectMapper = objectMapper;
    }

    /**
     * 应用方案：把方案编译为 FFmpeg 命令并渲染出片，同时持久化 RENDER 任务。
     */
    public RenderOutput render(Long projectId) {
        PlanEntity plan = planRepository.queryCurrentByProjectId(String.valueOf(projectId));
        if (plan == null) {
            throw new IllegalArgumentException("项目无方案可渲染: " + projectId);
        }

        java.util.Map<String, Object> payload = new java.util.HashMap<>();
        payload.put("projectId", projectId);
        TaskEntity task = taskDomainService.createPending(projectId, TaskType.RENDER,
                writeJson(payload));
        taskDomainService.start(task.getTaskId());

        try {
            createWorkDir();
            RenderCommand command = renderPlanService.compile(plan, workDir);
            RenderOutput output = renderEngine.render(command);
            output.setTaskId(task.getTaskId());
            taskDomainService.markSuccess(task.getTaskId(), toResultJson(output));
            return output;
        } catch (Exception e) {
            taskDomainService.markFailed(task.getTaskId(), e.getMessage());
            throw e;
        }
    }

    private void createWorkDir() {
        try {
            Files.createDirectories(Path.of(workDir));
        } catch (IOException e) {
            throw new IllegalStateException("创建渲染目录失败: " + workDir, e);
        }
    }

    private String toResultJson(RenderOutput output) {
        try {
            return objectMapper.writeValueAsString(output);
        } catch (Exception e) {
            return "{\"outputPath\":\"" + output.getOutputPath() + "\"}";
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("JSON 序列化失败: " + e.getMessage(), e);
        }
    }
}
