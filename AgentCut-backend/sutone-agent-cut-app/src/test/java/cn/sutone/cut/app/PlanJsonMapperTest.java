package cn.sutone.cut.app;

import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.model.valobj.Global;
import cn.sutone.cut.domain.plan.model.valobj.OpCrop;
import cn.sutone.cut.domain.plan.model.valobj.OpMute;
import cn.sutone.cut.domain.plan.model.valobj.OpSpeed;
import cn.sutone.cut.domain.plan.model.valobj.OpSubtitle;
import cn.sutone.cut.domain.plan.model.valobj.OpVolume;
import cn.sutone.cut.domain.plan.model.valobj.OutputConfig;
import cn.sutone.cut.domain.plan.model.valobj.Segment;
import cn.sutone.cut.domain.plan.model.valobj.Source;
import cn.sutone.cut.domain.plan.model.valobj.TimeRange;
import cn.sutone.cut.infrastructure.plan.PlanJsonMapper;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;

/**
 * 方案 JSON 序列化单元测试：验证 Operation 判别联合的多态往返。
 */
class PlanJsonMapperTest {

    @Test
    void operationRoundTrip() throws Exception {
        PlanJsonMapper mapper = new PlanJsonMapper();
        PlanEntity plan = PlanEntity.builder()
                .schemaVersion("1.0")
                .planVersion(1)
                .projectId("1")
                .source(Source.builder().assetId("a1").url("input.mp4").duration(60).fps(30).width(1920).height(1080).build())
                .global(Global.builder().output(OutputConfig.builder().width(1080).height(1920).fps(30).build()).build())
                .timeline(List.of(
                        Segment.builder().id("seg_1").keep(true)
                                .sourceRange(TimeRange.builder().start(0).end(10).build())
                                .operations(List.of(
                                        new OpSpeed(1.5),
                                        new OpCrop(0, 0, 1080, 1920),
                                        new OpSubtitle("你好'世界", 0, 5),
                                        new OpVolume(0.5),
                                        new OpMute()
                                )).build()
                ))
                .build();

        String json = mapper.toJson(plan);
        PlanEntity restored = mapper.fromJson(json);

        assertEquals(1, restored.getTimeline().size());
        Segment seg = restored.getTimeline().get(0);
        assertEquals(5, seg.getOperations().size());
        assertInstanceOf(OpSpeed.class, seg.getOperations().get(0));
        assertInstanceOf(OpCrop.class, seg.getOperations().get(1));
        assertInstanceOf(OpSubtitle.class, seg.getOperations().get(2));
        assertInstanceOf(OpVolume.class, seg.getOperations().get(3));
        assertInstanceOf(OpMute.class, seg.getOperations().get(4));

        OpSubtitle sub = (OpSubtitle) seg.getOperations().get(2);
        assertEquals("你好'世界", sub.getText());
    }
}
