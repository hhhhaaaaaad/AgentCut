package cn.sutone.cut.domain.asset.model.entity;

import cn.sutone.cut.domain.asset.model.valobj.enums.AssetType;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 素材实体（源视频/成片/BGM/封面）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AssetEntity {

    private Long assetId;
    private Long projectId;
    private AssetType type;
    /** OSS 地址 */
    private String ossUrl;
    private String fileName;
    private long size;
    private double duration;
    private int width;
    private int height;
    private double fps;
    private LocalDateTime createdAt;
}
