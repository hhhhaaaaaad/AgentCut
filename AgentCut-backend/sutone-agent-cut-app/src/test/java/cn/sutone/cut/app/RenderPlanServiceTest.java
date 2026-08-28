package cn.sutone.cut.app;

import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.model.valobj.Global;
import cn.sutone.cut.domain.plan.model.valobj.OpSpeed;
import cn.sutone.cut.domain.plan.model.valobj.OutputConfig;
import cn.sutone.cut.domain.plan.model.valobj.Segment;
import cn.sutone.cut.domain.plan.model.valobj.Source;
import cn.sutone.cut.domain.plan.model.valobj.TimeRange;
import cn.sutone.cut.domain.render.model.valobj.RenderCommand;
import cn.sutone.cut.domain.render.service.RenderPlanService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 方案编译服务单元测试：验证分段统一 + concat + 最终输出命令。
 */
class RenderPlanServiceTest {

    @Test
    void compileNormalizesSegmentsAndBuildsCommands() {
        PlanEntity plan = PlanEntity.builder()
                .schemaVersion("1.0")
                .planVersion(1)
                .projectId("1")
                .source(Source.builder().url("input.mp4").duration(100).fps(30).width(1920).height(1080).build())
                .global(Global.builder().output(OutputConfig.builder().width(1080).height(1920).fps(30).build()).build())
                .timeline(List.of(
                        Segment.builder().id("seg_1").keep(true)
                                .sourceRange(TimeRange.builder().start(0).end(10).build())
                                .operations(List.of(new OpSpeed(1.5))).build(),
                        Segment.builder().id("seg_2").keep(false)
                                .sourceRange(TimeRange.builder().start(10).end(20).build()).build()
                ))
                .build();

        RenderPlanService service = new RenderPlanService();
        RenderCommand cmd = service.compile(plan, "work");

        // keep=false 的段不渲染：1 个段 + concat + final = 3 条命令
        assertEquals(3, cmd.getCommands().size());

        // 分段命令：统一 scale/fps + 段内变速
        List<String> seg = cmd.getCommands().get(0);
        assertTrue(anyContains(seg, "scale=1080:1920"), "分段应统一分辨率");
        assertTrue(anyContains(seg, "fps=30.0"), "分段应统一帧率");
        assertTrue(anyContains(seg, "setpts=PTS/1.5"), "分段应含变速滤镜");

        // concat 命令
        assertTrue(anyContains(cmd.getCommands().get(1), "concat"), "应含 concat 拼接命令");

        // final 命令：copy
        assertTrue(anyContains(cmd.getCommands().get(2), "copy"), "最终命令应直接 copy");
    }

    private static boolean anyContains(List<String> args, String fragment) {
        return args.stream().anyMatch(a -> a.contains(fragment));
    }
}
