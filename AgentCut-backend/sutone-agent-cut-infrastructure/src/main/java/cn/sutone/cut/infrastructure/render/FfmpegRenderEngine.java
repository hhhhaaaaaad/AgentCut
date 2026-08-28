package cn.sutone.cut.infrastructure.render;

import cn.sutone.cut.domain.render.adapter.port.IRenderEngine;
import cn.sutone.cut.domain.render.model.valobj.RenderCommand;
import cn.sutone.cut.domain.render.model.valobj.RenderOutput;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * FFmpeg 渲染引擎实现：执行 {@link RenderCommand} 中的命令序列。
 */
@Component
public class FfmpegRenderEngine implements IRenderEngine {

    private static final Logger log = LoggerFactory.getLogger(FfmpegRenderEngine.class);

    @Override
    public RenderOutput render(RenderCommand command) {
        // 1. 写 concat 列表文件（concat demuxer 依赖）
        if (command.getConcatListPath() != null && command.getConcatListFiles() != null
                && !command.getConcatListFiles().isEmpty()) {
            writeConcatList(command.getConcatListPath(), command.getConcatListFiles());
        }

        // 2. 逐条执行 ffmpeg 命令
        for (List<String> argv : command.getCommands()) {
            execute(argv);
        }

        // 3. 返回产物（补全成片元信息：大小 + 时长）
        Path output = Path.of(command.getOutputPath());
        long size = fileSize(output);
        double duration = probeDuration(output);
        return RenderOutput.builder()
                .outputPath(command.getOutputPath())
                .duration(duration)
                .size(size)
                .build();
    }

    /**
     * 读取成片文件大小（字节）；失败返回 0。
     */
    private long fileSize(Path file) {
        try {
            return Files.size(file);
        } catch (IOException e) {
            log.warn("读取成片大小失败: {}", e.getMessage());
            return 0L;
        }
    }

    /**
     * 用 ffprobe 探测成片时长（秒）；失败返回 0。
     */
    private double probeDuration(Path file) {
        try {
            ProcessBuilder pb = new ProcessBuilder("ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file.toString());
            pb.redirectErrorStream(true);
            Process p = pb.start();
            String out;
            try (var in = p.getInputStream()) {
                out = new String(in.readAllBytes(), StandardCharsets.UTF_8).trim();
            }
            p.waitFor();
            return out.isEmpty() ? 0.0 : Double.parseDouble(out);
        } catch (Exception e) {
            log.warn("探测成片时长失败: {}", e.getMessage());
            return 0.0;
        }
    }

    /**
     * 执行单条命令（ProcessBuilder）。
     */
    private void execute(List<String> argv) {
        try {
            log.info("执行命令: {}", String.join(" ", argv));
            ProcessBuilder pb = new ProcessBuilder(argv);
            pb.redirectErrorStream(true);
            Process process = pb.start();
            // 骨架：简化处理，读取输出避免阻塞
            try (var in = process.getInputStream()) {
                in.readAllBytes();
            }
            int exit = process.waitFor();
            if (exit != 0) {
                throw new IllegalStateException("ffmpeg 命令执行失败，exit=" + exit);
            }
        } catch (IOException e) {
            throw new IllegalStateException("ffmpeg 不可用，请确认已安装并加入 PATH", e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("ffmpeg 命令被中断", e);
        }
    }

    /**
     * 写 concat demuxer 列表文件（格式：file 'xxx.mp4'）。
     */
    private void writeConcatList(String listPath, List<String> files) {
        try {
            StringBuilder sb = new StringBuilder();
            for (String f : files) {
                // concat demuxer 的列表相对路径是相对列表文件所在目录，只需写文件名
                String name = f.replace("\\", "/");
                int idx = name.lastIndexOf('/');
                if (idx >= 0) {
                    name = name.substring(idx + 1);
                }
                sb.append("file '").append(name).append("'\n");
            }
            Files.writeString(Path.of(listPath), sb.toString(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("写 concat 列表文件失败: " + listPath, e);
        }
    }
}
