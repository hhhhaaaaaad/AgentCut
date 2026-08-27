package cn.sutone.cut.api.dto;

import lombok.Data;

/**
 * 分析请求（用户意图约束，替代长期记忆）。
 */
@Data
public class AnalyzeRequestDTO {

    /** 目标画幅，如 "9:16" */
    private String aspectRatio;
    /** 目标时长（秒） */
    private Integer maxDuration;
    /** 是否加字幕 */
    private Boolean addSubtitle;
    /** 风格意图（自由文本） */
    private String style;
}
