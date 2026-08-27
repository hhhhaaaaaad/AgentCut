package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.plan.adapter.repository.IPlanRepository;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.service.PlanDomainService;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 方案应用服务（查询/保存/版本/回滚）。
 */
@Service
public class PlanService {

    private final IPlanRepository planRepository;
    private final PlanDomainService planDomainService;

    public PlanService(IPlanRepository planRepository, PlanDomainService planDomainService) {
        this.planRepository = planRepository;
        this.planDomainService = planDomainService;
    }

    public PlanEntity queryPlan(Long projectId) {
        return planRepository.queryCurrentByProjectId(projectId);
    }

    public void savePlan(PlanEntity plan) {
        planDomainService.savePlan(plan);
    }

    public List<Integer> versions(Long projectId) {
        return planRepository.queryVersionNumbers(projectId);
    }

    public String rollback(Long projectId, int versionNo) {
        return planDomainService.rollback(projectId, versionNo);
    }
}
