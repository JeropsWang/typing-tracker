-- 打字管家 SQLite 表结构（M1）

-- 每日快照（正确率/平均速度只存在这里，不并入终身总计）
CREATE TABLE IF NOT EXISTS daily_stats (
  date           TEXT PRIMARY KEY,          -- 'YYYY-MM-DD'（按日切起点归属）
  typed_chars    INTEGER NOT NULL DEFAULT 0,
  deleted_chars  INTEGER NOT NULL DEFAULT 0,
  valid_chars    INTEGER NOT NULL DEFAULT 0,
  total_tw       INTEGER NOT NULL DEFAULT 0,
  active_minutes INTEGER NOT NULL DEFAULT 0,
  avg_tw         REAL,                      -- 日平均速度（仅日指标）
  accuracy       REAL,                      -- 日正确率（仅日指标）
  exp_gained     INTEGER NOT NULL DEFAULT 0
);

-- 分钟粒度（成就"每分钟正确率"用；保留近 30 日由后续里程碑做清理）
CREATE TABLE IF NOT EXISTS minute_stats (
  date          TEXT NOT NULL,
  minute        TEXT NOT NULL,              -- 'HH:MM'
  typed_chars   INTEGER NOT NULL DEFAULT 0,
  deleted_chars INTEGER NOT NULL DEFAULT 0,
  total_tw      INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (date, minute)
);

-- 终身总计（只有总量类指标，无平均速度/正确率）
CREATE TABLE IF NOT EXISTS lifetime (
  id                 INTEGER PRIMARY KEY CHECK (id = 1),
  total_typed        INTEGER NOT NULL DEFAULT 0,
  total_deleted      INTEGER NOT NULL DEFAULT 0,
  total_tw           INTEGER NOT NULL DEFAULT 0,
  total_active_minutes INTEGER NOT NULL DEFAULT 0,
  total_exp          INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO lifetime(id) VALUES (1);

-- 打卡与连签
CREATE TABLE IF NOT EXISTS checkin_log (
  date      TEXT PRIMARY KEY,
  streak    INTEGER NOT NULL DEFAULT 1,     -- 当日连签天数
  base_exp  INTEGER NOT NULL DEFAULT 0,
  bonus_exp INTEGER NOT NULL DEFAULT 0,
  card_used INTEGER NOT NULL DEFAULT 0
);

-- 成就（37 项，M3 启用）
CREATE TABLE IF NOT EXISTS achievements (
  code        TEXT PRIMARY KEY,             -- 如 speed_500 / acc_95
  unlocked_at TEXT NOT NULL,
  claimed     INTEGER NOT NULL DEFAULT 0    -- 0=待领取 1=已领取
);

-- 道具库存（补签卡 / 经验加成卡 / 称号）
CREATE TABLE IF NOT EXISTS rewards (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  kind       TEXT NOT NULL,                 -- makeup_card | exp_boost | exp | title
  qty        INTEGER NOT NULL DEFAULT 1,
  source     TEXT,
  note       TEXT,                          -- 如称号名
  created_at TEXT NOT NULL,
  used_at    TEXT
);

-- 设置（单位名、日切起点、无限等级、排除程序、等级段名、主题等）
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
