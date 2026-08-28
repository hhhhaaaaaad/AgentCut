package cn.sutone.cut.trigger.http;

import cn.sutone.cut.api.dto.AssetDTO;
import cn.sutone.cut.app.service.AssetService;
import cn.sutone.cut.domain.asset.model.entity.AssetEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 素材接口（上传/列表/查询/删除）。
 */
@RestController
@RequestMapping("/api/v1")
public class AssetController {

    private final AssetService assetService;

    public AssetController(AssetService assetService) {
        this.assetService = assetService;
    }

    /** 上传视频素材（multipart/form-data，字段名 file） */
    @PostMapping("/projects/{projectId}/upload")
    public AssetDTO upload(@PathVariable Long projectId, @RequestParam("file") MultipartFile file) throws Exception {
        AssetEntity asset = assetService.upload(projectId,
                file.getOriginalFilename(), file.getContentType(), file.getBytes());
        return toDTO(asset);
    }

    @GetMapping("/projects/{projectId}/assets")
    public List<AssetDTO> list(@PathVariable Long projectId) {
        return assetService.listByProject(projectId).stream().map(this::toDTO).toList();
    }

    @GetMapping("/assets/{assetId}")
    public AssetDTO query(@PathVariable Long assetId) {
        return toDTO(assetService.query(assetId));
    }

    @DeleteMapping("/assets/{assetId}")
    public void delete(@PathVariable Long assetId) {
        assetService.delete(assetId);
    }

    private AssetDTO toDTO(AssetEntity e) {
        if (e == null) {
            return null;
        }
        return AssetDTO.builder()
                .assetId(e.getAssetId())
                .projectId(e.getProjectId())
                .type(e.getType() != null ? e.getType().name() : null)
                .ossUrl(e.getOssUrl())
                .fileName(e.getFileName())
                .size(e.getSize())
                .duration(e.getDuration())
                .width(e.getWidth())
                .height(e.getHeight())
                .fps(e.getFps())
                .build();
    }
}
