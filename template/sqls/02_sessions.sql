-- 会话相关表：sessions / messages
-- 字段与 app/model/session.py 的 ORM 模型保持一致

-- 会话元信息
CREATE TABLE IF NOT EXISTS `sessions` (
  `id`                INT           NOT NULL AUTO_INCREMENT                           COMMENT '会话自增主键',
  `session_id`        VARCHAR(64)   NOT NULL                                        COMMENT '会话业务标识（对外暴露，全局唯一）',
  `user_id`           INT           NOT NULL                                        COMMENT '所属用户 id（对应 users.id，不建外键）',
  `channel`           VARCHAR(32)   NOT NULL DEFAULT 'web'                          COMMENT '接入渠道（web / app / im）',
  `title`             VARCHAR(128)  NOT NULL DEFAULT '新会话'                        COMMENT '会话名称（可重命名）',
  `status`            VARCHAR(32)   NOT NULL DEFAULT 'active'                       COMMENT '会话状态（active / handoff / closed）',
  `summary`           TEXT          DEFAULT NULL                                    COMMENT '运行摘要（running_summary）',
  `created_at`        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP             COMMENT '创建时间',
  `updated_at`        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间（每次写入消息时刷新，用于会话列表排序）',
  `deleted_at`        TIMESTAMP     DEFAULT NULL                                    COMMENT '软删除时间（NULL 表示未删除）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_sessions_session_id` (`session_id`),
  KEY `idx_sessions_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话元信息表';

-- 会话消息流
CREATE TABLE IF NOT EXISTS `messages` (
  `id`                 INT           NOT NULL AUTO_INCREMENT                       COMMENT '消息自增主键',
  `session_id`         VARCHAR(64)   NOT NULL                                      COMMENT '所属会话标识（对应 sessions.session_id）',
  `role`               VARCHAR(16)   NOT NULL                                      COMMENT '消息角色（user / assistant / system / tool）',
  `message_type`       VARCHAR(32)   NOT NULL DEFAULT 'text'                       COMMENT '消息类型（text / summary / tool_result / clarification）',
  `content`            TEXT          NOT NULL                                      COMMENT '原始消息文本',
  `sanitized_content`  TEXT          NOT NULL                                      COMMENT '清洗后内容（脱敏/标准化，用于展示与检索）',
  `sequence_no`        INT           NOT NULL DEFAULT 0                            COMMENT '会话内顺序号（append_message 时取 max+1，保证历史回放顺序）',
  `created_at`         TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP           COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_messages_session_id` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话消息流表';
