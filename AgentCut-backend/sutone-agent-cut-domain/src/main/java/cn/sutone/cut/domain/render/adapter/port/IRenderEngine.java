package cn.sutone.cut.domain.render.adapter.port;

import cn.sutone.cut.domain.render.model.valobj.RenderCommand;
import cn.sutone.cut.domain.render.model.valobj.RenderOutput;

/**
 * 渲染引擎端口（FFmpeg 实现）。
 */
public interface IRenderEngine {

    /**
     * 执行渲染命令序列，返回成片产物。
     */
    RenderOutput render(RenderCommand command);
}
