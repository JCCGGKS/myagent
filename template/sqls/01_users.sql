-- 用户表：开放注册、找回密码
CREATE TABLE IF NOT EXISTS `users` (
  `id`            INT           NOT NULL AUTO_INCREMENT                           COMMENT '用户自增主键',
  `username`      VARCHAR(64)   NOT NULL                                        COMMENT '用户名（唯一，用于登录）',
  `email`         VARCHAR(255)  NOT NULL                                        COMMENT '邮箱（唯一，用于找回密码）',
  `password_hash` VARCHAR(255)  NOT NULL                                        COMMENT '密码哈希（bcrypt）',
  `created_at`    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP             COMMENT '创建时间',
  `updated_at`    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_username` (`username`),
  UNIQUE KEY `uk_users_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='平台用户表（开放注册）';
