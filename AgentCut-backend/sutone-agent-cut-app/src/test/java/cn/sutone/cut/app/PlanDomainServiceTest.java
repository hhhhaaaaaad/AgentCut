package cn.sutone.cut.app;

import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.model.valobj.Segment;
import cn.sutone.cut.domain.plan.model.valobj.Source;
import cn.sutone.cut.domain.plan.model.valobj.TimeRange;
import cn.sutone.cut.domain.plan.service.PlanDomainService;
import cn.sutone.cut.infrastructure.persistence.plan.InMemoryPlanRepository;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * 方案领域服务校验单元测试：时间区间合法、片段不超出源视频时长。
 */
class PlanDomainServiceTest {

    private final PlanDomainService service = new PlanDomainService(new InMemoryPlanRepository());

    private PlanEntity validPlan() {
        return PlanEntity.builder()
                .schemaVersion("1.0")
                .planVersion(1)
                .projectId("1")
                .source(Source.builder().url("input.mp4").duration(60).fps(30).width(1920).height(1080).build())
                .timeline(List.of(
                        Segment.builder().id("seg_1").keep(true)
                                .sourceRange(TimeRange.builder().start(0).end(10).build()).build()
                ))
                .build();
    }

    @Test
    void validatePassesForValidPlan() {
        assertDoesNotThrow(() -> service.validate(validPlan()));
    }

    @Test
    void validateRejectsNullSource() {
        PlanEntity plan = validPlan();
        plan.setSource(null);
        assertThrows(IllegalArgumentException.class, () -> service.validate(plan));
    }

    @Test
    void validateRejectsNullSourceRange() {
        PlanEntity plan = validPlan();
        plan.getTimeline().get(0).setSourceRange(null);
        assertThrows(IllegalArgumentException.class, () -> service.validate(plan));
    }

    @Test
    void validateRejectsEndBeforeOrEqualStart() {
        PlanEntity plan = validPlan();
        plan.getTimeline().get(0).setSourceRange(TimeRange.builder().start(10).end(10).build());
        assertThrows(IllegalArgumentException.class, () -> service.validate(plan));
    }

    @Test
    void validateRejectsSegmentExceedingDuration() {
        PlanEntity plan = validPlan();
        plan.getTimeline().get(0).setSourceRange(TimeRange.builder().start(0).end(61).build());
        assertThrows(IllegalArgumentException.class, () -> service.validate(plan));
    }
}
