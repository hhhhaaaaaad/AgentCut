package cn.sutone.cut.domain.asset.adapter.repository;

import cn.sutone.cut.domain.asset.model.entity.AssetEntity;

import java.util.List;

/**
 * 素材仓储接口。
 */
public interface IAssetRepository {

    void save(AssetEntity asset);

    AssetEntity queryById(Long assetId);

    List<AssetEntity> queryByProjectId(Long projectId);

    void delete(Long assetId);
}
