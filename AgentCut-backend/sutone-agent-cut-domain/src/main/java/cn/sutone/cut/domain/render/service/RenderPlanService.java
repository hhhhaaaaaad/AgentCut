package cn.sutone.cut.domain.render.service;

import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.model.valobj.OpCrop;
import cn.sutone.cut.domain.plan.model.valobj.OpMute;
import cn.sutone.cut.domain.plan.model.valobj.OpSpeed;
import cn.sutone.cut.domain.plan.model.valobj.OpSubtitle;
import cn.sutone.cut.domain.plan.model.valobj.OpVolume;
import cn.sutone.cut.domain.plan.model.valobj.Operation;
import cn.sutone.cut.domain.plan.model.valobj.OutputConfig;
import cn.sutone.cut.domain.plan.model.valobj.Segment;
import cn.sutone.cut.domain.plan.model.valobj.Source;
import cn.sutone.cut.domain.render.model.valobj.RenderCommand;

import java.util.ArrayList;
import java.util.List;

/**
 * 方案编译服务：把 Plan 编译成 FFmpeg 命令中间表示（IR）。
 *
 * <p>纯函数、无副作用，便于单测。MVP 编译策略：
 * ① 每个 keep 段 → 一条 ffmpeg 命令（trim + 段内 op）；
 * ② 全部段 → concat 拼接；
 * ③ 拼接结果 + 输出配置（scale/pad）+ BGM → 最终成片。</p>
 */
public class RenderPlanService {

    private static final String FFMPEG = "ffmpeg";

    /**
     * 编译方案为渲染命令序列。
     *
     * @param plan    剪辑方案
     * @param workDir 中间产物目录
     */
    public RenderCommand compile(PlanEntity plan, String workDir) {
        List<List<String>> commands = new ArrayList<>();
        Source source = plan.getSource();
        String input = source.getUrl();
        String concatListPath = workDir + "/concat_list.txt";

        // ① 逐段渲染
        List<String> segmentFiles = new ArrayList<>();
        List<Segment> kept = plan.keptSegments();
        for (int i = 0; i < kept.size(); i++) {
            Segment seg = kept.get(i);
            String segFile = workDir + "/seg_" + i + ".mp4";
            segmentFiles.add(segFile);
            commands.add(buildSegmentCommand(input, seg, segFile));
        }

        // ② concat 拼接
        String concatFile = workDir + "/concat.mp4";
        commands.add(buildConcatCommand(segmentFiles, concatListPath, concatFile));

        // ③ 最终输出（输出配置 + BGM）
        String outputPath = workDir + "/output.mp4";
        commands.add(buildFinalCommand(concatFile, plan, outputPath));

        return RenderCommand.builder()
                .commands(commands)
                .outputPath(outputPath)
                .concatListPath(concatListPath)
                .concatListFiles(segmentFiles)
                .build();
    }

    /**
     * 构建单段渲染命令：trim + 段内操作。
     */
    private List<String> buildSegmentCommand(String input, Segment seg, String output) {
        List<String> cmd = new ArrayList<>();
        cmd.add(FFMPEG);
        cmd.add("-y");
        cmd.add("-ss");
        cmd.add(String.valueOf(seg.getSourceRange().getStart()));
        cmd.add("-t");
        cmd.add(String.valueOf(seg.getSourceRange().getEnd() - seg.getSourceRange().getStart()));
        cmd.add("-i");
        cmd.add(input);

        List<String> vf = new ArrayList<>();
        List<String> af = new ArrayList<>();
        for (Operation op : seg.getOperations()) {
            switch (op.type()) {
                case SPEED -> {
                    OpSpeed s = (OpSpeed) op;
                    vf.add("setpts=PTS/" + s.getRate());
                    af.add("atempo=" + s.getRate());
                }
                case CROP -> {
                    OpCrop c = (OpCrop) op;
                    vf.add("crop=" + c.getWidth() + ":" + c.getHeight() + ":" + c.getX() + ":" + c.getY());
                }
                case SUBTITLE -> {
                    OpSubtitle sub = (OpSubtitle) op;
                    vf.add("drawtext=text='" + sub.getText() + "':enable='between(t," + sub.getStart() + "," + sub.getEnd() + ")'");
                }
                case VOLUME -> {
                    OpVolume v = (OpVolume) op;
                    af.add("volume=" + v.getVolume());
                }
                case MUTE -> af.add("volume=0");
            }
        }

        if (!vf.isEmpty()) {
            cmd.add("-vf");
            cmd.add(String.join(",", vf));
        }
        if (!af.isEmpty()) {
            cmd.add("-af");
            cmd.add(String.join(",", af));
        }
        cmd.add("-c:v");
        cmd.add("libx264");
        cmd.add("-c:a");
        cmd.add("aac");
        cmd.add(output);
        return cmd;
    }

    /**
     * 构建 concat 拼接命令（concat demuxer）。
     */
    private List<String> buildConcatCommand(List<String> segmentFiles, String listPath, String output) {
        List<String> cmd = new ArrayList<>();
        cmd.add(FFMPEG);
        cmd.add("-y");
        cmd.add("-f");
        cmd.add("concat");
        cmd.add("-safe");
        cmd.add("0");
        cmd.add("-i");
        cmd.add(listPath);
        cmd.add("-c");
        cmd.add("copy");
        cmd.add(output);
        return cmd;
    }

    /**
     * 构建最终输出命令：缩放/画幅 + 可选 BGM。
     */
    private List<String> buildFinalCommand(String concatFile, PlanEntity plan, String output) {
        List<String> cmd = new ArrayList<>();
        cmd.add(FFMPEG);
        cmd.add("-y");
        cmd.add("-i");
        cmd.add(concatFile);

        OutputConfig out = plan.getGlobal() != null ? plan.getGlobal().getOutput() : null;
        if (out != null) {
            cmd.add("-vf");
            cmd.add("scale=" + out.getWidth() + ":" + out.getHeight());
        }

        cmd.add("-c:v");
        cmd.add("libx264");
        cmd.add("-c:a");
        cmd.add("aac");
        cmd.add(output);
        return cmd;
    }
}
