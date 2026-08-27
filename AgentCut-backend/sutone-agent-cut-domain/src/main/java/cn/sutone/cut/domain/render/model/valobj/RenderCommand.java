package cn.sutone.cut.domain.render.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * 渲染中间表示（IR）：plan 编译产出的 FFmpeg 命令序列。
 *
 * <p>每个元素是一条 ffmpeg 命令的 argv 数组，供执行引擎逐条执行。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RenderCommand {

    /** 按顺序执行的 ffmpeg 命令 argv 列表 */
    @Builder.Default
    private List<List<String>> commands = new ArrayList<>();

    /** 最终成片输出路径 */
    private String outputPath;

    /** concat 列表文件路径（concat demuxer 需要） */
    private String concatListPath;

    /** 需写入 concat 列表的段文件路径 */
    @Builder.Default
    private List<String> concatListFiles = new ArrayList<>();
}
