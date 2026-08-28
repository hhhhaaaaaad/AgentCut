-- =============================================================
-- AgentCut 数据库初始化脚本（MySQL 8.0+）
-- 对应 docs/AgentCut-整体设计方案.md 第 10 章「数据库设计」
--
-- 说明：当前 MVP 骨架用内存仓储（InMemory*Repository），不依赖本库。
-- 本脚本用于切换到 MyBatis 持久化时建表。
-- =============================================================

CREATE DATABASE IF NOT EXISTS agentcut
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE agentcut;

-- -------------------------------------------------------------
-- 项目
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '项目ID',
    user_id         BIGINT       NOT NULL DEFAULT 0 COMMENT '用户ID（单用户MVP固定0，多租户预留）',
    title           VARCHAR(255) NOT NULL DEFAULT '' COMMENT '标题',
    source_asset_id BIGINT       NULL COMMENT '源视频素材ID',
    status          VARCHAR(32)  NOT NULL DEFAULT 'DRAFT' COMMENT '状态',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_project_user (user_id)
) ENGINE = InnoDB COMMENT = '剪辑项目';

-- -------------------------------------------------------------
-- 素材
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS asset (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '素材ID',
    project_id BIGINT       NOT NULL COMMENT '所属项目',
    type       VARCHAR(16)  NOT NULL COMMENT 'SOURCE/OUTPUT/BGM/THUMBNAIL',
    oss_url    VARCHAR(512) NOT NULL DEFAULT '' COMMENT 'OSS地址',
    file_name  VARCHAR(255) NOT NULL DEFAULT '',
    size       BIGINT       NOT NULL DEFAULT 0 COMMENT '字节',
    duration   DOUBLE       NOT NULL DEFAULT 0 COMMENT '时长(秒)',
    width      INT          NOT NULL DEFAULT 0,
    height     INT          NOT NULL DEFAULT 0,
    fps        DOUBLE       NOT NULL DEFAULT 0,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_asset_project (project_id)
) ENGINE = InnoDB COMMENT = '素材';

-- -------------------------------------------------------------
-- 分析报告
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_report (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id   BIGINT      NOT NULL,
    version      INT         NOT NULL DEFAULT 1,
    content_json JSON        NULL COMMENT '报告内容（场景/转写/亮点/建议）',
    status       VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
    created_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_report_project (project_id)
) ENGINE = InnoDB COMMENT = '分析报告';

-- -------------------------------------------------------------
-- 剪辑方案（主表，记录当前生效版本）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plan (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id         BIGINT      NOT NULL,
    current_version_id BIGINT      NULL COMMENT '当前生效版本ID',
    status             VARCHAR(32) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT/READY/APPLIED',
    created_at         DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_plan_project (project_id)
) ENGINE = InnoDB COMMENT = '剪辑方案';

-- -------------------------------------------------------------
-- 方案版本（存档 / 回滚）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plan_version (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    plan_id      BIGINT   NOT NULL,
    version_no   INT      NOT NULL,
    content_json JSON     NOT NULL COMMENT '方案内容（对齐 docs/plan-schema.json）',
    applied      TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已应用',
    created_by   BIGINT   NULL,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_plan_version (plan_id, version_no)
) ENGINE = InnoDB COMMENT = '方案版本';

-- -------------------------------------------------------------
-- 异步任务（ANALYZE / RENDER）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS task (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id   BIGINT       NOT NULL,
    type         VARCHAR(16)  NOT NULL COMMENT 'ANALYZE/RENDER',
    status       VARCHAR(16)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/RUNNING/SUCCESS/FAILED/RETRYING',
    progress     INT          NOT NULL DEFAULT 0 COMMENT '进度 0-100',
    payload_json JSON         NULL COMMENT '入参',
    result_json  JSON         NULL COMMENT '结果',
    error_msg    VARCHAR(1024) NULL,
    heartbeat_at DATETIME     NULL,
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_task_project (project_id)
) ENGINE = InnoDB COMMENT = '异步任务';

-- -------------------------------------------------------------
-- Outbox 事件（消息可靠性，对齐 AgentWrite 的 Outbox 模式）
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outbox_event (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(64)  NOT NULL,
    topic      VARCHAR(128) NOT NULL,
    payload    JSON         NULL,
    status     VARCHAR(16)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/PUBLISHED',
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB COMMENT = 'Outbox 事件';
