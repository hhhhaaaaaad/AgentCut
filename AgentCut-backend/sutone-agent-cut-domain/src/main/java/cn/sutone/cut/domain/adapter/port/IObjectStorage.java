package cn.sutone.cut.domain.adapter.port;

/**
 * 对象存储端口（MinIO/OSS）。
 */
public interface IObjectStorage {

    /**
     * 上传文件，返回可访问的 URL。
     */
    String upload(String objectName, byte[] content, String contentType);

    /**
     * 生成可访问 URL（用于传给 Python 分析）。
     */
    String getUrl(String objectName);

    /**
     * 删除对象。
     */
    void delete(String objectName);
}
