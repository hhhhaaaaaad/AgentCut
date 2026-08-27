package cn.sutone.cut.infrastructure.persistence.asset;

import cn.sutone.cut.domain.asset.adapter.repository.IAssetRepository;
import cn.sutone.cut.domain.asset.model.entity.AssetEntity;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 素材仓储 MVP 内存实现。后续替换为 MyBatis Mapper。
 */
@Repository
public class InMemoryAssetRepository implements IAssetRepository {

    private final Map<Long, AssetEntity> store = new ConcurrentHashMap<>();
    private final AtomicLong idGen = new AtomicLong(1);

    @Override
    public void save(AssetEntity asset) {
        if (asset.getAssetId() == null) {
            asset.setAssetId(idGen.getAndIncrement());
        }
        store.put(asset.getAssetId(), asset);
    }

    @Override
    public AssetEntity queryById(Long assetId) {
        return store.get(assetId);
    }

    @Override
    public List<AssetEntity> queryByProjectId(Long projectId) {
        return store.values().stream().filter(a -> projectId.equals(a.getProjectId())).toList();
    }
}
