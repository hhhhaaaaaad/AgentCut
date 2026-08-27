package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.plan.adapter.repository.IPlanRepository;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.render.adapter.port.IRenderEngine;
import cn.sutone.cut.domain.render.model.valobj.RenderCommand;
import cn.sutone.cut.domain.render.model.valobj.RenderOutput;
import cn.sutone.cut.domain.render.service.RenderPlanService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 渲染任务编排：读方案 → 编译 → FFmpeg 渲染 → 成片。
 */
@Service
public class RenderTaskService {

    private final IPlanRepository planRepository;
    private final RenderPlanService renderPlanService;
    private final IRenderEngine renderEngine;

    @Value("${agentcut.render.work-dir:./data/work}")
    private String workDir;

    public RenderTaskService(IPlanRepository planRepository, RenderPlanService renderPlanService,
                             IRenderEngine renderEngine) {
        this.planRepository = planRepository;
        this.renderPlanService = renderPlanService;
        this.renderEngine = renderEngine;
    }

    /**
     * 应用方案：把方案编译为 FFmpeg 命令并渲染出片。
     */
    public RenderOutput render(Long projectId) {
        PlanEntity plan = planRepository.queryCurrentByProjectId(projectId);
        if (plan == null) {
            throw new IllegalArgumentException("项目无方案可渲染: " + projectId);
        }
        RenderCommand command = renderPlanService.compile(plan, workDir);
        return renderEngine.render(command);
    }
}
