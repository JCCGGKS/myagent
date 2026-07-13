-- 可观测事件流表：event_logs
-- 每一轮对话的决策链（intent/state/tool_result/final/error）落库，供按 trace_id 回放。
-- 字段与 app/model/session.py 的 EventLog ORM 模型保持一致。
-- 与 messages 解耦：messages 给前端渲染，event_logs 给排障回放（详见 plans/observability-trace-plan.md）。

CREATE TABLE IF NOT EXISTS `event_logs` (
  `id`          INT           NOT NULL AUTO_INCREMENT                       COMMENT '事件自增主键',
  `session_id`  VARCHAR(64)   NOT NULL                                      COMMENT '所属会话标识（对应 sessions.session_id）',
  `trace_id`    VARCHAR(64)   NOT NULL                                      COMMENT '本轮追踪 id（每轮请求生成，串联全部事件）',
  `turn`        INT           NOT NULL DEFAULT 0                            COMMENT '会话内轮次（用于多轮排序，按 trace_id 分组即可还原单轮）',
  `event_type`  VARCHAR(32)   NOT NULL                                      COMMENT '事件类型 intent/state/tool_result/final/error/policy',
  `node`        VARCHAR(64)   DEFAULT NULL                                  COMMENT '产生事件的图节点名（可选）',
  `payload`     TEXT          NOT NULL                                      COMMENT '完整事件 JSON（含结构化字段）',
  `created_at`  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP           COMMENT '创建时间（回放按此排序）',
  PRIMARY KEY (`id`),
  KEY `idx_event_logs_session_id` (`session_id`),
  KEY `idx_event_logs_trace_id` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='可观测事件流落库表';
