package cn.sutone.cut.domain.plan.model.entity;

import cn.sutone.cut.domain.plan.model.valobj.Global;
import cn.sutone.cut.domain.plan.model.valobj.Segment;
import cn.sutone.cut.domain.plan.model.valobj.Source;
import cn.sutone.cut.domain.plan.model.valobj.Transition;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * 剪辑方案聚合根。
 *
 * <p>字段与 docs/plan-schema.json 严格对齐。这是 Agent 生成、人可编辑、引擎可执行的唯一事实来源。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PlanEntity {

    /** Schema 版本（契约） */
    private String schemaVersion;
    /** 方案自身版本号（存档/回滚用） */
    private int planVersion;
    /** 所属项目 ID（契约字段，plan-schema.json 定义为 string） */
    private String projectId;
    /** 方案标题 */
    private String title;
    /** 源视频信息 */
    private Source source;
    /** 全局设置 */
    private Global global;
    /** 时间线片段（顺序即最终顺序） */
    @Builder.Default
    private List<Segment> timeline = new ArrayList<>();
    /** 段间转场 */
    @Builder.Default
    private List<Transition> transitions = new ArrayList<>();

    /**
     * 返回保留的片段（keep=true），按时间线顺序。
     */
    public List<Segment> keptSegments() {
        return timeline.stream().filter(Segment::isKeep).toList();
    }
}
