package cn.sutone.cut.infrastructure.persistence.plan;

import cn.sutone.cut.domain.plan.adapter.repository.IPlanRepository;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.infrastructure.persistence.mapper.PlanMapper;
import cn.sutone.cut.infrastructure.plan.PlanJsonMapper;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * 剪辑方案仓储 MyBatis 实现（mysql profile）。
 *
 * <p>方案 JSON 存于 plan_version.content_json，当前版本由 plan.current_version_id 指向；
 * 查询当前方案时 join 取回 JSON 后用 {@link PlanJsonMapper} 反序列化。</p>
 */
@Repository
@Profile("mysql")
public class MybatisPlanRepository implements IPlanRepository {

    private final PlanMapper planMapper;
    private final PlanJsonMapper planJsonMapper;

    public MybatisPlanRepository(PlanMapper planMapper, PlanJsonMapper planJsonMapper) {
        this.planMapper = planMapper;
        this.planJsonMapper = planJsonMapper;
    }

    @Override
    public void save(PlanEntity plan) {
        planMapper.upsertPlan(toProjectId(plan.getProjectId()));
    }

    @Override
    public PlanEntity queryCurrentByProjectId(String projectId) {
        String json = planMapper.selectCurrentContent(toProjectId(projectId));
        if (json == null) {
            return null;
        }
        try {
            return planJsonMapper.fromJson(json);
        } catch (Exception e) {
            throw new IllegalStateException("方案 JSON 解析失败: " + e.getMessage(), e);
        }
    }

    @Override
    public void saveVersion(String projectId, int versionNo, String contentJson) {
        Long pid = toProjectId(projectId);
        planMapper.upsertPlan(pid);
        Long planId = planMapper.selectPlanId(pid);
        if (planId == null) {
            throw new IllegalStateException("方案主表记录不存在: " + projectId);
        }
        planMapper.upsertVersion(planId, versionNo, contentJson);
        planMapper.updateCurrentVersion(planId, versionNo);
    }

    @Override
    public List<Integer> queryVersionNumbers(String projectId) {
        Long planId = planMapper.selectPlanId(toProjectId(projectId));
        return planId == null ? List.of() : planMapper.selectVersionNumbers(planId);
    }

    @Override
    public String queryVersionContent(String projectId, int versionNo) {
        Long planId = planMapper.selectPlanId(toProjectId(projectId));
        return planId == null ? null : planMapper.selectVersionContent(planId, versionNo);
    }

    @Override
    public int nextVersionNo(String projectId) {
        Long planId = planMapper.selectPlanId(toProjectId(projectId));
        if (planId == null) {
            return 1;
        }
        Integer max = planMapper.selectMaxVersionNo(planId);
        return max == null ? 1 : max + 1;
    }

    private Long toProjectId(String projectId) {
        try {
            return Long.parseLong(projectId);
        } catch (NumberFormatException e) {
            throw new IllegalStateException("方案 projectId 非数字，无法持久化: " + projectId, e);
        }
    }
}
