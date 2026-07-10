-- 知识库文件元信息表：记录上传文件 + 入库状态
-- 字段与 app/model/knowledge.py 的 ORM 模型保持一致
-- 主键 id 同时作为文档标识（doc_id），同文件切出的所有 chunk 在 Qdrant payload 中存此 id，用于按文档删向量
-- status 用 TINYINT：0=processing 1=success 2=error
CREATE TABLE IF NOT EXISTS `knowledge_files` (
  `id`             INT           NOT NULL AUTO_INCREMENT                           COMMENT '自增主键，同时作为文档标识 doc_id（写入 Qdrant payload，按文档删向量）',
  `user_id`        INT           NOT NULL                                        COMMENT '所属用户 id（对应 users.id，不建外键）',
  `filename`       VARCHAR(255)  NOT NULL                                        COMMENT '原始文件名',
  `file_size`      INT           NOT NULL                                        COMMENT '文件大小（字节数）',
  `doc_type`       VARCHAR(32)   NOT NULL                                        COMMENT '文档类型（markdown / json）',
  `chunk_count`    INT           NOT NULL DEFAULT 0                              COMMENT '入库分块数',
  `status`         TINYINT       NOT NULL DEFAULT 0                              COMMENT 'ingest status (0=processing处理中 1=success成功 2=error失败)',
  `error_message`  VARCHAR(500)  DEFAULT NULL                                    COMMENT '失败原因（status=2 时写入）',
  `created_at`     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP             COMMENT '上传时间（列表按此字段倒序）',
  `updated_at`     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted_at`     TIMESTAMP     DEFAULT NULL                                    COMMENT '软删除时间（NULL 表示未删除，列表过滤）',
  PRIMARY KEY (`id`),
  KEY `idx_knowledge_files_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文件元信息表';
