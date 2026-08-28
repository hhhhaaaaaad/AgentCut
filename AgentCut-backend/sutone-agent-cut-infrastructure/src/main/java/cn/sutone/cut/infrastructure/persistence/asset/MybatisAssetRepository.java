package cn.sutone.cut.infrastructure.persistence.asset;

import cn.sutone.cut.domain.asset.adapter.repository.IAssetRepository;
import cn.sutone.cut.domain.asset.model.entity.AssetEntity;
import cn.sutone.cut.infrastructure.persistence.mapper.AssetMapper;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * 素材仓储 MyBatis 实现（mysql profile）。
 */
@Repository
@Profile("mysql")
public class MybatisAssetRepository implements IAssetRepository {

    private final AssetMapper assetMapper;

    public MybatisAssetRepository(AssetMapper assetMapper) {
        this.assetMapper = assetMapper;
    }

    @Override
    public void save(AssetEntity asset) {
        assetMapper.insert(asset);
    }

    @Override
    public AssetEntity queryById(Long assetId) {
        return assetMapper.selectById(assetId);
    }

    @Override
    public List<AssetEntity> queryByProjectId(Long projectId) {
        return assetMapper.selectByProjectId(projectId);
    }

    @Override
    public void delete(Long assetId) {
        assetMapper.delete(assetId);
    }
}
