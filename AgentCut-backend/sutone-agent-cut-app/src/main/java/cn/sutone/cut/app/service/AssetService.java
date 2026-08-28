package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.adapter.port.IObjectStorage;
import cn.sutone.cut.domain.asset.adapter.repository.IAssetRepository;
import cn.sutone.cut.domain.asset.model.entity.AssetEntity;
import cn.sutone.cut.domain.asset.model.valobj.enums.AssetType;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 素材应用服务：上传 / 列表 / 查询 / 删除。
 */
@Service
public class AssetService {

    private final IAssetRepository assetRepository;
    private final IObjectStorage objectStorage;

    public AssetService(IAssetRepository assetRepository, IObjectStorage objectStorage) {
        this.assetRepository = assetRepository;
        this.objectStorage = objectStorage;
    }

    /**
     * 上传素材文件：存对象存储 + 建 SOURCE 素材记录。
     */
    public AssetEntity upload(Long projectId, String fileName, String contentType, byte[] content) {
        String name = (fileName == null || fileName.isBlank()) ? "upload" : fileName;
        String objectName = "project/" + projectId + "/" + UUID.randomUUID() + "_" + name;
        String url = objectStorage.upload(objectName, content,
                contentType == null ? "application/octet-stream" : contentType);

        AssetEntity asset = AssetEntity.builder()
                .projectId(projectId)
                .type(AssetType.SOURCE)
                .ossUrl(url)
                .fileName(name)
                .size(content.length)
                .createdAt(LocalDateTime.now())
                .build();
        assetRepository.save(asset);
        return asset;
    }

    public List<AssetEntity> listByProject(Long projectId) {
        return assetRepository.queryByProjectId(projectId);
    }

    public AssetEntity query(Long assetId) {
        return assetRepository.queryById(assetId);
    }

    /**
     * 删除素材（存储对象删除待接入：AssetEntity 目前只存 URL，未存 objectName）。
     */
    public void delete(Long assetId) {
        assetRepository.delete(assetId);
    }
}
