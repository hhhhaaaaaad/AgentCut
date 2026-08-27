package cn.sutone.cut.domain.adapter.port;

/**
 * 视频分析客户端端口（调用 Python 分析服务）。
 */
public interface IVideoAnalysisClient {

    /**
     * 提交分析任务到 Python 服务。
     *
     * @param videoUrl   源视频 URL（OSS/http）
     * @param callbackUrl 分析完成回调地址（Java 侧）
     * @param targetJson 用户意图约束 JSON（画幅/时长/字幕/风格）
     * @return Python 侧 jobId
     */
    String submitAnalyze(String videoUrl, String callbackUrl, String targetJson);

    /**
     * 查询 Python 侧分析任务状态。
     *
     * @param jobId Python 侧 jobId
     * @return 状态 JSON
     */
    String queryStatus(String jobId);
}
