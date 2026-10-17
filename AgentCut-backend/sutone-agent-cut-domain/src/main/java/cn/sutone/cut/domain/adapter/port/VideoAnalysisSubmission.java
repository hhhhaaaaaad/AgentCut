package cn.sutone.cut.domain.adapter.port;

/**
 * Python 分析服务的受理结果。
 *
 * @param jobId  Python 任务 ID
 * @param status Python 返回的受理状态
 */
public record VideoAnalysisSubmission(String jobId, String status) {
}
