package cn.sutone.cut.infrastructure.persistence.plan;

import cn.sutone.cut.domain.plan.adapter.repository.IPlanRepository;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import org.springframework.stereotype.Repository;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 剪辑方案仓储 MVP 内存实现。
 *
 * <p>后续替换为 MyBatis Mapper（plan / plan_version 两张表）。</p>
 */
@Repository
public class InMemoryPlanRepository implements IPlanRepository {

    private final Map<Long, PlanEntity> current = new ConcurrentHashMap<>();
    private final Map<Long, Map<Integer, String>> versions = new ConcurrentHashMap<>();

    @Override
    public void save(PlanEntity plan) {
        current.put(plan.getProjectId(), plan);
    }

    @Override
    public PlanEntity queryCurrentByProjectId(Long projectId) {
        return current.get(projectId);
    }

    @Override
    public void saveVersion(Long projectId, int versionNo, String contentJson) {
        versions.computeIfAbsent(projectId, k -> new ConcurrentHashMap<>()).put(versionNo, contentJson);
    }

    @Override
    public List<Integer> queryVersionNumbers(Long projectId) {
        Map<Integer, String> map = versions.get(projectId);
        return map == null ? List.of() : new ArrayList<>(map.keySet());
    }

    @Override
    public String queryVersionContent(Long projectId, int versionNo) {
        Map<Integer, String> map = versions.get(projectId);
        return map == null ? null : map.get(versionNo);
    }
}
