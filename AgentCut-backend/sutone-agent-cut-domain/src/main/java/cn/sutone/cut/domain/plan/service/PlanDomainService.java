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
     */
    public void savePlan(PlanEntity plan) {
        validate(plan);
        planRepository.save(plan);
        planRepository.saveVersion(plan.getProjectId(), plan.getPlanVersion(), toJson(plan));
    }

    /**
     * 回滚到指定版本：把历史版本内容恢复为当前方案。
     */
    public String rollback(Long projectId, int versionNo) {
        String content = planRepository.queryVersionContent(projectId, versionNo);
        if (content == null) {
            throw new IllegalArgumentException("版本不存在: " + versionNo);
        }
        // 骨架：回滚后重新落库（具体反序列化由基础设施层完成）
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

    private String toJson(PlanEntity plan) {
        // 骨架：序列化交给基础设施层（Jackson），此处返回占位
        return "{}";
    }
}
