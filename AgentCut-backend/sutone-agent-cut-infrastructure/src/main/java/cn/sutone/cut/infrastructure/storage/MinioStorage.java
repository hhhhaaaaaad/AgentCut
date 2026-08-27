package cn.sutone.cut.infrastructure.storage;

import cn.sutone.cut.domain.adapter.port.IObjectStorage;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * 对象存储实现。
 *
 * <p>MVP 用本地文件系统占位（写本地目录并返回 file:// URL），后续替换为 MinIO SDK。</p>
 */
@Component
public class MinioStorage implements IObjectStorage {

    @Value("${agentcut.storage.local-dir:./data}")
    private String localDir;

    @Override
    public String upload(String objectName, byte[] content, String contentType) {
        try {
            Path target = Path.of(localDir, objectName);
            Files.createDirectories(target.getParent());
            Files.write(target, content);
            return "file://" + target.toAbsolutePath();
        } catch (IOException e) {
            throw new IllegalStateException("存储文件失败: " + objectName, e);
        }
    }

    @Override
    public String getUrl(String objectName) {
        return "file://" + Path.of(localDir, objectName).toAbsolutePath();
    }

    @Override
    public void delete(String objectName) {
        try {
            Files.deleteIfExists(Path.of(localDir, objectName));
        } catch (IOException e) {
            throw new IllegalStateException("删除文件失败: " + objectName, e);
        }
    }
}
