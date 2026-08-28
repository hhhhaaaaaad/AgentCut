package cn.sutone.cut.domain.render.service;

import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.model.valobj.OpCrop;
import cn.sutone.cut.domain.plan.model.valobj.OpSpeed;
import cn.sutone.cut.domain.plan.model.valobj.OpSubtitle;
import cn.sutone.cut.domain.plan.model.valobj.OpVolume;
import cn.sutone.cut.domain.plan.model.valobj.Operation;
import cn.sutone.cut.domain.plan.model.valobj.OutputConfig;
import cn.sutone.cut.domain.plan.model.valobj.Segment;
import cn.sutone.cut.domain.plan.model.valobj.Source;
import cn.sutone.cut.domain.plan.model.valobj.SubtitleStyle;
import cn.sutone.cut.domain.render.model.valobj.RenderCommand;

import java.util.ArrayList;
import java.util.List;

/**
 * 方案编译服务：把 Plan 编译成 FFmpeg 命令中间表示（IR）。
 *
 * <p>纯函数、无副作用，便于单测。编译策略：
 * ① 每个 keep 段 → 一条 ffmpeg 命令（trim + 段内 op + 统一分辨率/帧率/采样率）；
 * ② 全部段 → concat 拼接；
 * ③ 拼接结果 → 最终成片（可选 BGM）。</p>
 *
 * <p>关键点：分段渲染时统一 scale/fps/采样率，保证 {@code concat -c copy} 能成功拼接
 * （concat demuxer 要求各段编码参数一致，否则报错或花屏）。</p>
 */
public class RenderPlanService {

    private static final String FFMPEG = "ffmpeg";

    /** 中文字体路径（drawtext 渲染字幕用）；空则用 FFmpeg 默认字体（不支持中文）。 */
    private final String subtitleFont;

    public RenderPlanService() {
        this(null);
    }

    public RenderPlanService(String subtitleFont) {
        this.subtitleFont = subtitleFont;
    }

    /**
     * 编译方案为渲染命令序列。
     *
     * @param plan    剪辑方案
     * @param workDir 中间产物目录
     */
    public RenderCommand compile(PlanEntity plan, String workDir) {
        List<List<String>> commands = new ArrayList<>();
        Source source = plan.getSource();
        OutputConfig out = plan.getGlobal() != null ? plan.getGlobal().getOutput() : null;
        SubtitleStyle subtitleStyle = plan.getGlobal() != null ? plan.getGlobal().getSubtitleStyle() : null;
        String input = normalizeUrl(source.getUrl());
        String concatListPath = workDir + "/concat_list.txt";

        // ① 逐段渲染（统一分辨率/帧率/采样率）
        List<String> segmentFiles = new ArrayList<>();
        List<Segment> kept = plan.keptSegments();
        for (int i = 0; i < kept.size(); i++) {
            Segment seg = kept.get(i);
            String segFile = workDir + "/seg_" + i + ".mp4";
            segmentFiles.add(segFile);
            commands.add(buildSegmentCommand(input, seg, segFile, out, source, subtitleStyle));
        }

        // ② concat 拼接
        String concatFile = workDir + "/concat.mp4";
        commands.add(buildConcatCommand(segmentFiles, concatListPath, concatFile));

        // ③ 最终输出
        String outputPath = workDir + "/output.mp4";
        commands.add(buildFinalCommand(concatFile, outputPath));

        return RenderCommand.builder()
                .commands(commands)
                .outputPath(outputPath)
                .concatListPath(concatListPath)
                .concatListFiles(segmentFiles)
                .build();
    }

    /**
     * 构建单段渲染命令：trim + 段内操作 + 统一输出参数。
     */
    private List<String> buildSegmentCommand(String input, Segment seg, String output,
                                             OutputConfig out, Source source, SubtitleStyle subtitleStyle) {
        List<String> cmd = new ArrayList<>();
        cmd.add(FFMPEG);
        cmd.add("-y");
        cmd.add("-ss");
        cmd.add(String.valueOf(seg.getSourceRange().getStart()));
        cmd.add("-t");
        cmd.add(String.valueOf(seg.getSourceRange().getEnd() - seg.getSourceRange().getStart()));
        cmd.add("-i");
        cmd.add(input);

        // 目标输出参数（无全局配置时回退到源参数）
        double targetW = out != null && out.getWidth() > 0 ? out.getWidth() : source.getWidth();
        double targetH = out != null && out.getHeight() > 0 ? out.getHeight() : source.getHeight();
        double targetFps = out != null && out.getFps() > 0 ? out.getFps() : source.getFps();

        List<String> vf = new ArrayList<>();
        List<String> af = new ArrayList<>();
        // 字幕滤镜延后到 scale 之后渲染，避免字号被放大（fontsize 应按最终分辨率）
        List<String> subtitles = new ArrayList<>();
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
                    subtitles.add(buildDrawtext(sub, subtitleStyle));
                }
                case VOLUME -> {
                    OpVolume v = (OpVolume) op;
                    af.add("volume=" + v.getVolume());
                }
                case MUTE -> af.add("volume=0");
            }
        }

        // 统一分辨率 + 帧率（concat 前置条件）
        vf.add("scale=" + (int) targetW + ":" + (int) targetH);
        vf.add("fps=" + targetFps);
        // 字幕在 scale 之后渲染，字号按最终分辨率 1:1 生效
        vf.addAll(subtitles);
        // 统一采样率
        af.add("aresample=44100");

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
        cmd.add("-ar");
        cmd.add("44100");
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
     * 构建最终输出命令（段已统一，直接 copy；BGM 混合待接入素材库）。
     */
    private List<String> buildFinalCommand(String concatFile, String output) {
        List<String> cmd = new ArrayList<>();
        cmd.add(FFMPEG);
        cmd.add("-y");
        cmd.add("-i");
        cmd.add(concatFile);
        // TODO: global.bgm 有 URL 时下载后 amix 混合
        cmd.add("-c");
        cmd.add("copy");
        cmd.add(output);
        return cmd;
    }

    /**
     * 构建 drawtext 字幕滤镜：指定中文字体 + 字号/颜色 + 时间区间。
     */
    private String buildDrawtext(OpSubtitle sub, SubtitleStyle style) {
        String text = escapeFilterText(sub.getText());
        StringBuilder dt = new StringBuilder("drawtext=");
        if (subtitleFont != null && !subtitleFont.isBlank()) {
            // 字体路径统一正斜杠，冒号转义（filter 参数分隔符）
            String font = subtitleFont.replace("\\", "/").replace(":", "\\:");
            dt.append("fontfile='").append(font).append("':");
        }
        dt.append("text='").append(text).append("'");
        if (style != null) {
            if (style.getFontSize() > 0) {
                dt.append(":fontsize=").append(style.getFontSize());
            }
            if (style.getColor() != null && !style.getColor().isBlank()) {
                dt.append(":fontcolor=").append(style.getColor());
            }
            if ("bottom".equalsIgnoreCase(style.getPosition())) {
                dt.append(":x=(main_w-text_w)/2:y=main_h-text_h-40");
            }
        }
        dt.append(":enable='between(t,").append(sub.getStart()).append(",").append(sub.getEnd()).append(")'");
        return dt.toString();
    }

    /**
     * 转义 drawtext 文本（text= 值包裹在单引号内，需转义反斜杠与单引号）。
     *
     * <p>最佳实践是用 textfile= 写临时文件，此处用最小转义兜底。</p>
     */
    private String escapeFilterText(String text) {
        if (text == null) {
            return "";
        }
        return text.replace("\\", "\\\\").replace("'", "\\'");
    }

    /**
     * 规范化输入 URL：本地存储 MVP 返回 file:// 前缀，FFmpeg 需纯文件路径。
     */
    private String normalizeUrl(String url) {
        if (url != null && url.startsWith("file://")) {
            return url.substring("file://".length());
        }
        return url;
    }
}
