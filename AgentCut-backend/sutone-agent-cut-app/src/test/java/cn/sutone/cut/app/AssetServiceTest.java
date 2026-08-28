package cn.sutone.cut.app;

import cn.sutone.cut.app.service.AssetService;
import cn.sutone.cut.domain.adapter.port.IObjectStorage;
import cn.sutone.cut.domain.asset.model.entity.AssetEntity;
import cn.sutone.cut.domain.asset.model.valobj.enums.AssetType;
import cn.sutone.cut.infrastructure.persistence.asset.InMemoryAssetRepository;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 素材应用服务单元测试：上传建立 SOURCE 素材。
 */
class AssetServiceTest {

    @Test
    void uploadCreatesSourceAssetAndPersists() {
        InMemoryAssetRepository assetRepository = new InMemoryAssetRepository();
        IObjectStorage storage = mock(IObjectStorage.class);
        when(storage.upload(anyString(), any(), anyString())).thenReturn("file:///data/project/1/x.mp4");

        AssetService service = new AssetService(assetRepository, storage);
        AssetEntity asset = service.upload(1L, "test_video.mp4", "video/mp4", new byte[]{1, 2, 3});

        assertNotNull(asset.getAssetId());
        assertEquals(AssetType.SOURCE, asset.getType());
        assertEquals(1L, asset.getProjectId());
        assertEquals("test_video.mp4", asset.getFileName());
        assertEquals(3L, asset.getSize());
        assertEquals("file:///data/project/1/x.mp4", asset.getOssUrl());

        AssetEntity loaded = assetRepository.queryById(asset.getAssetId());
        assertNotNull(loaded);
        assertEquals(AssetType.SOURCE, loaded.getType());

        verify(storage, times(1)).upload(anyString(), any(), anyString());
    }

    @Test
    void uploadUsesDefaultsForBlankNameAndNullContentType() {
        InMemoryAssetRepository assetRepository = new InMemoryAssetRepository();
        IObjectStorage storage = mock(IObjectStorage.class);
        when(storage.upload(anyString(), any(), anyString())).thenReturn("file:///x");

        AssetService service = new AssetService(assetRepository, storage);
        AssetEntity asset = service.upload(1L, "  ", null, new byte[0]);

        assertEquals("upload", asset.getFileName());
        verify(storage).upload(anyString(), any(), eq("application/octet-stream"));
    }
}
