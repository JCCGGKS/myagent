-- 会话相关表：sessions / messages / state_snapshots / tool_calls / handoff_records
-- 字段与 app/model/session.py 的 ORM 模型保持一致

-- 会话元信息
CREATE TABLE IF NOT EXISTS `sessions` (
  `session_id`        VARCHAR(64)   NOT NULL,
  `user_id`           VARCHAR(64)   NOT NULL,
  `channel`           VARCHAR(32)   NOT NULL DEFAULT 'web',
  `status`            VARCHAR(32)   NOT NULL DEFAULT 'active',
  `current_intent`    VARCHAR(64)   DEFAULT NULL,
  `current_stage`     VARCHAR(64)   DEFAULT NULL,
  `risk_level`        VARCHAR(16)   DEFAULT NULL,
  `summary`           TEXT          DEFAULT NULL,
  `handoff_required`  TINYINT(1)    NOT NULL DEFAULT 0,
  `created_at`        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`session_id`),
  KEY `idx_sessions_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 会话消息流
CREATE TABLE IF NOT EXISTS `messages` (
  `id`                 BIGINT        NOT NULL AUTO_INCREMENT,
  `session_id`         VARCHAR(64)   NOT NULL,
  `role`               VARCHAR(16)   NOT NULL,
  `message_type`       VARCHAR(32)   NOT NULL DEFAULT 'text',
  `content`            TEXT          NOT NULL,
  `sanitized_content`  TEXT          NOT NULL,
  `sequence_no`        INT           NOT NULL DEFAULT 0,
  `created_at`         TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_messages_session_id` (`session_id`),
  CONSTRAINT `fk_messages_session` FOREIGN KEY (`session_id`) REFERENCES `sessions` (`session_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 会话状态快照
CREATE TABLE IF NOT EXISTS `state_snapshots` (
  `id`                   BIGINT        NOT NULL AUTO_INCREMENT,
  `session_id`           VARCHAR(64)   NOT NULL,
  `current_intent`       VARCHAR(64)   DEFAULT NULL,
  `sub_intent`           VARCHAR(64)   DEFAULT NULL,
  `stage`                VARCHAR(64)   DEFAULT NULL,
  `slots`                JSON          DEFAULT NULL,
  `missing_slots`        JSON          DEFAULT NULL,
  `confirmed_slots`      JSON          DEFAULT NULL,
  `candidate_intents`    JSON          DEFAULT NULL,
  `needs_clarification`  TINYINT(1)    NOT NULL DEFAULT 0,
  `topic_changed`        TINYINT(1)    NOT NULL DEFAULT 0,
  `risk_level`           VARCHAR(16)   DEFAULT NULL,
  `state_summary`        TEXT          DEFAULT NULL,
  `running_summary`      TEXT          DEFAULT NULL,
  `current_action`       VARCHAR(64)   DEFAULT NULL,
  `latest_action_result` JSON          DEFAULT NULL,
  `created_at`           TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_state_snapshots_session_id` (`session_id`),
  CONSTRAINT `fk_state_snapshots_session` FOREIGN KEY (`session_id`) REFERENCES `sessions` (`session_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 工具调用审计
CREATE TABLE IF NOT EXISTS `tool_calls` (
  `id`                   BIGINT        NOT NULL AUTO_INCREMENT,
  `session_id`           VARCHAR(64)   NOT NULL,
  `tool_name`            VARCHAR(64)   NOT NULL,
  `tool_category`        VARCHAR(32)   NOT NULL DEFAULT 'query',
  `request_args`         JSON          DEFAULT NULL,
  `raw_result`           JSON          DEFAULT NULL,
  `sanitized_result`     JSON          DEFAULT NULL,
  `user_facing_summary`  TEXT          DEFAULT NULL,
  `status`               VARCHAR(16)   NOT NULL DEFAULT 'success',
  `created_at`           TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_tool_calls_session_id` (`session_id`),
  CONSTRAINT `fk_tool_calls_session` FOREIGN KEY (`session_id`) REFERENCES `sessions` (`session_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 转人工记录
CREATE TABLE IF NOT EXISTS `handoff_records` (
  `id`              BIGINT        NOT NULL AUTO_INCREMENT,
  `session_id`      VARCHAR(64)   NOT NULL,
  `handoff_reason`  VARCHAR(64)   DEFAULT NULL,
  `handoff_summary` TEXT          DEFAULT NULL,
  `state_snapshot`  JSON          DEFAULT NULL,
  `status`          VARCHAR(16)   NOT NULL DEFAULT 'pending',
  `created_at`      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_handoff_records_session_id` (`session_id`),
  CONSTRAINT `fk_handoff_records_session` FOREIGN KEY (`session_id`) REFERENCES `sessions` (`session_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
