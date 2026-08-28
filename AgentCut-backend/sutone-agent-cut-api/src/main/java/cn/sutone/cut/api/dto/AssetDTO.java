package cn.sutone.cut.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 素材响应 DTO。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AssetDTO {

    private Long assetId;
    private Long projectId;
    private String type;
    private String ossUrl;
    private String fileName;
    private long size;
    private double duration;
    private int width;
    private int height;
    private double fps;
}
