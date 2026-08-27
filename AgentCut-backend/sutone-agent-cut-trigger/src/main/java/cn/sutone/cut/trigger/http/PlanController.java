package cn.sutone.cut.trigger.http;

import cn.sutone.cut.app.service.PlanService;
import cn.sutone.cut.app.service.RenderTaskService;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.render.model.valobj.RenderOutput;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 剪辑方案接口（查询/保存/版本/回滚/应用）。
 */
@RestController
@RequestMapping("/api/v1")
public class PlanController {

    private final PlanService planService;
    private final RenderTaskService renderTaskService;

    public PlanController(PlanService planService, RenderTaskService renderTaskService) {
        this.planService = planService;
        this.renderTaskService = renderTaskService;
    }

    @GetMapping("/plans/{projectId}")
    public PlanEntity queryPlan(@PathVariable Long projectId) {
        return planService.queryPlan(projectId);
    }

    /** 保存方案（生成新版本） */
    @PutMapping("/plans/{projectId}")
    public void savePlan(@PathVariable Long projectId, @RequestBody PlanEntity plan) {
        plan.setProjectId(projectId);
        planService.savePlan(plan);
    }

    @GetMapping("/plans/{projectId}/versions")
    public List<Integer> versions(@PathVariable Long projectId) {
        return planService.versions(projectId);
    }

    @PostMapping("/plans/{projectId}/versions/{versionNo}/rollback")
    public String rollback(@PathVariable Long projectId, @PathVariable int versionNo) {
        return planService.rollback(projectId, versionNo);
    }

    /** 应用方案：编译 FFmpeg 命令并渲染出片 */
    @PostMapping("/plans/{projectId}/apply")
    public RenderOutput apply(@PathVariable Long projectId) {
        return renderTaskService.render(projectId);
    }
}
