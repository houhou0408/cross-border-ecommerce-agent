-- ============================================================
-- 跨境电商 AI Agent 数据库初始化脚本
-- 用途：1) 查询日志统计  2) Listing 生成存档  3) 关税/汇率快照
-- ============================================================

CREATE DATABASE IF NOT EXISTS cross_border_agent
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE cross_border_agent;

-- 1. 查询日志表：记录每次 Agent 调用的输入/输出/耗时/工具链
CREATE TABLE IF NOT EXISTS query_log (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id    VARCHAR(64)  NOT NULL COMMENT '会话ID',
  user_query    TEXT         NOT NULL COMMENT '用户问题',
  agent_answer  MEDIUMTEXT   NULL     COMMENT 'Agent最终回答',
  tools_used    VARCHAR(512) NULL     COMMENT '调用的工具链(JSON)',
  retrievals    INT          NULL     COMMENT '召回文档数',
  grounded      TINYINT(1)   NULL     COMMENT '是否通过幻觉校验',
  latency_ms    INT          NULL     COMMENT '端到端耗时(毫秒)',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_session (session_id),
  INDEX idx_created (created_at)
) ENGINE=InnoDB COMMENT='Agent查询日志';

-- 2. Listing 存档表：保存生成的产品 Listing
CREATE TABLE IF NOT EXISTS listing_archive (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  product_name  VARCHAR(255) NOT NULL COMMENT '产品名称',
  platform      VARCHAR(64)  NOT NULL COMMENT '目标平台(amazon/shopee/temu)',
  language      VARCHAR(16)  NOT NULL COMMENT '语言(en/zh)',
  title         VARCHAR(512) NULL     COMMENT '生成标题',
  bullets       MEDIUMTEXT   NULL     COMMENT '五点描述(JSON)',
  description   MEDIUMTEXT   NULL     COMMENT '详情描述',
  keywords      VARCHAR(512) NULL     COMMENT '搜索关键词',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_platform (platform)
) ENGINE=InnoDB COMMENT='Listing生成存档';

-- 3. 汇率快照表：缓存汇率，减少外部调用
CREATE TABLE IF NOT EXISTS exchange_rate (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  from_currency VARCHAR(8)  NOT NULL,
  to_currency   VARCHAR(8)  NOT NULL,
  rate          DECIMAL(12,6) NOT NULL,
  source        VARCHAR(32) NULL,
  updated_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_pair (from_currency, to_currency)
) ENGINE=InnoDB COMMENT='汇率快照';

-- 4. 关税规则表：简化版 HS 编码关税查询
CREATE TABLE IF NOT EXISTS tariff_rule (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  country       VARCHAR(64) NOT NULL COMMENT '目的国',
  category      VARCHAR(128) NOT NULL COMMENT '商品类别',
  hs_code       VARCHAR(16) NULL     COMMENT 'HS编码',
  tariff_rate   DECIMAL(6,4) NOT NULL COMMENT '关税税率(0~1)',
  note          VARCHAR(255) NULL,
  UNIQUE KEY uniq_country_cat (country, category)
) ENGINE=InnoDB COMMENT='关税规则';

-- 5. 会话表：多轮对话历史（user_id 实现按用户隔离）
CREATE TABLE IF NOT EXISTS chat_session (
  id          VARCHAR(32)  PRIMARY KEY COMMENT '会话ID',
  title       VARCHAR(255) NOT NULL DEFAULT '新对话',
  user_id     VARCHAR(32)  NULL COMMENT '归属用户ID；NULL为遗留数据，列表不返回',
  created_at  DATETIME     NOT NULL,
  updated_at  DATETIME     NOT NULL,
  INDEX idx_session_user (user_id),
  INDEX idx_updated (updated_at)
) ENGINE=InnoDB COMMENT='对话会话（记忆模块）';

-- 6. 会话消息表
CREATE TABLE IF NOT EXISTS chat_message (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id  VARCHAR(32)  NOT NULL,
  role        VARCHAR(16)  NOT NULL COMMENT 'user/assistant',
  content     MEDIUMTEXT   NOT NULL,
  meta        MEDIUMTEXT   NULL COMMENT '工具链/评分等元数据(JSON)',
  created_at  DATETIME     NOT NULL,
  INDEX idx_msg_session (session_id)
) ENGINE=InnoDB COMMENT='会话消息（记忆模块）';

-- 7. 视频生成任务表（user_id 归属，MySQL 优先 / JSON 文件降级）
CREATE TABLE IF NOT EXISTS video_task (
  id           VARCHAR(12) PRIMARY KEY,
  user_id      VARCHAR(32)  NULL,
  username     VARCHAR(100),
  prompt       TEXT,
  image_url    VARCHAR(500),
  mode         VARCHAR(10)  COMMENT 'i2v/r2v/t2v',
  status       VARCHAR(20)  COMMENT 'processing/completed',
  video_url    VARCHAR(1000),
  used_fallback TINYINT,
  created_at   VARCHAR(32),
  completed_at VARCHAR(32),
  INDEX idx_video_user (user_id)
) ENGINE=InnoDB COMMENT='视频生成任务';

-- 8. 卖点图生成任务表（images 列存 JSON：{type: {name,url,fallback}}）
CREATE TABLE IF NOT EXISTS image_task (
  id           VARCHAR(12) PRIMARY KEY,
  user_id      VARCHAR(32)  NULL,
  username     VARCHAR(100),
  product      VARCHAR(500),
  features     TEXT,
  image_url    VARCHAR(500),
  status       VARCHAR(20),
  images       MEDIUMTEXT,
  used_fallback TINYINT,
  created_at   VARCHAR(32),
  completed_at VARCHAR(32),
  INDEX idx_image_user (user_id)
) ENGINE=InnoDB COMMENT='卖点图生成任务';

-- ===== 存量库迁移（已有旧表时执行；列已存在会报 1060，可忽略）=====
-- ALTER TABLE chat_session ADD COLUMN user_id VARCHAR(32) NULL, ADD INDEX idx_session_user (user_id);
-- 存量无主会话回填给管理员（按需执行）：
-- UPDATE chat_session SET user_id = 'admin-user-id' WHERE user_id IS NULL;

-- ===== 预置示例数据（演示用）=====
INSERT INTO exchange_rate (from_currency, to_currency, rate, source)
VALUES
  ('CNY','USD',0.1390,'mock'),
  ('USD','CNY',7.1950,'mock'),
  ('CNY','EUR',0.1280,'mock'),
  ('USD','EUR',0.9200,'mock'),
  ('CNY','JPY',21.4000,'mock')
ON DUPLICATE KEY UPDATE rate=VALUES(rate), updated_at=NOW();

INSERT INTO tariff_rule (country, category, hs_code, tariff_rate, note) VALUES
  ('美国','电子产品','8543.70',0.2500,'部分品类加征301关税'),
  ('美国','服装','6109.10',0.1630,'棉制T恤'),
  ('美国','家居用品','3924.10',0.0350,'塑料制品'),
  ('欧盟','电子产品','8543.70',0.1400,'需CE认证'),
  ('欧盟','服装','6109.10',0.1200,'棉制T恤'),
  ('日本','电子产品','8543.70',0.0000,'多数电子零关税'),
  ('日本','服装','6109.10',0.0910,'棉制T恤')
ON DUPLICATE KEY UPDATE tariff_rate=VALUES(tariff_rate);
