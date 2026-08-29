package cn.sutone.cut.domain.analysis.model.entity;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 分析报告实体（Python Agent 产出）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AnalysisReportEntity {

    private Long reportId;
    private Long projectId;
    private int version;
    /** 报告内容 JSON（场景/转写/亮点/建议） */
    private String contentJson;
    /** 质量评审 JSON（Plan 的质检结果，raw JSON 原样落库，暂挂 analysis_report 仅为最小改动） */
    private String qualityJson;
    private String status;
    private LocalDateTime createdAt;
}
