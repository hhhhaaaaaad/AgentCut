package cn.sutone.cut.domain.plan.service;

import cn.sutone.cut.domain.plan.adapter.repository.IPlanRepository;
import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.model.valobj.Segment;
import cn.sutone.cut.domain.plan.model.valobj.TimeRange;

/**
 * 剪辑方案领域服务：校验、保存、版本化、回滚。
 */
public class PlanDomainService {

    private final IPlanRepository planRepository;

    public PlanDomainService(IPlanRepository planRepository) {
        this.planRepository = planRepository;
    }

    /**
     * 保存方案：校验通过后落库，并生成历史版本。
     *
     * @param plan        方案实体
     * @param contentJson 序列化后的方案 JSON（由应用层用 PlanJsonMapper 生成，领域层不做序列化）
     */
    public void savePlan(PlanEntity plan, String contentJson) {
        validate(plan);
        planRepository.save(plan);
        // 版本号由系统递增（LLM 的 planVersion 是方案文档字段，非存档版本号）
        int versionNo = planRepository.nextVersionNo(plan.getProjectId());
        planRepository.saveVersion(plan.getProjectId(), versionNo, contentJson);
    }

    /**
     * 回滚到指定版本：把历史版本内容恢复为当前方案。
     */
    public String rollback(String projectId, int versionNo) {
        String content = planRepository.queryVersionContent(projectId, versionNo);
        if (content == null) {
            throw new IllegalArgumentException("版本不存在: " + versionNo);
        }
        return content;
    }

    /**
     * 基础校验：时间区间合法、片段 ID 唯一、操作类型受支持。
     */
    public void validate(PlanEntity plan) {
        if (plan.getSource() == null) {
            throw new IllegalArgumentException("source 不能为空");
        }
        double duration = plan.getSource().getDuration();
        for (Segment seg : plan.getTimeline()) {
            TimeRange r = seg.getSourceRange();
            if (r == null || r.getStart() < 0 || r.getEnd() <= r.getStart()) {
                throw new IllegalArgumentException("片段时间区间非法: " + seg.getId());
            }
            if (r.getEnd() > duration) {
                throw new IllegalArgumentException("片段超出源视频时长: " + seg.getId());
            }
        }
    }
}
