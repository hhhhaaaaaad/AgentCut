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
     * @return Python 侧受理结果（包含 jobId）
     */
    VideoAnalysisSubmission submitAnalyze(String videoUrl, String callbackUrl, String targetJson);
}
