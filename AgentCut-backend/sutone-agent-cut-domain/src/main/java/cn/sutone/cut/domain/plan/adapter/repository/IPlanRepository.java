package cn.sutone.cut.domain.plan.adapter.repository;

import cn.sutone.cut.domain.plan.model.entity.PlanEntity;

import java.util.List;

/**
 * 剪辑方案仓储接口（含版本化）。
 */
public interface IPlanRepository {

    /** 保存当前生效方案 */
    void save(PlanEntity plan);

    /** 按项目查询当前方案 */
    PlanEntity queryCurrentByProjectId(Long projectId);

    /** 保存一个历史版本 */
    void saveVersion(Long projectId, int versionNo, String contentJson);

    /** 查询某项目的版本号列表 */
    List<Integer> queryVersionNumbers(Long projectId);

    /** 查询某项目指定版本的内容 JSON */
    String queryVersionContent(Long projectId, int versionNo);
}
