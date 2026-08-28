package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.plan.adapter.repository.IPlanRepository;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.service.PlanDomainService;
import cn.sutone.cut.infrastructure.plan.PlanJsonMapper;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 方案应用服务（查询/保存/版本/回滚）。
 */
@Service
public class PlanService {

    private final IPlanRepository planRepository;
    private final PlanDomainService planDomainService;
    private final PlanJsonMapper planJsonMapper;

    public PlanService(IPlanRepository planRepository, PlanDomainService planDomainService,
                       PlanJsonMapper planJsonMapper) {
        this.planRepository = planRepository;
        this.planDomainService = planDomainService;
        this.planJsonMapper = planJsonMapper;
    }

    public PlanEntity queryPlan(Long projectId) {
        return planRepository.queryCurrentByProjectId(String.valueOf(projectId));
    }

    public void savePlan(PlanEntity plan) {
        try {
            String contentJson = planJsonMapper.toJson(plan);
            planDomainService.savePlan(plan, contentJson);
        } catch (Exception e) {
            throw new IllegalStateException("方案序列化失败: " + e.getMessage(), e);
        }
    }

    public List<Integer> versions(Long projectId) {
        return planRepository.queryVersionNumbers(String.valueOf(projectId));
    }

    public String rollback(Long projectId, int versionNo) {
        return planDomainService.rollback(String.valueOf(projectId), versionNo);
    }
}
