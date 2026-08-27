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

        // 3. 返回产物
        return RenderOutput.builder()
                .outputPath(command.getOutputPath())
                .build();
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
                sb.append("file '").append(f.replace("\\", "/")).append("'\n");
            }
            Files.writeString(Path.of(listPath), sb.toString(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("写 concat 列表文件失败: " + listPath, e);
        }
    }
}
