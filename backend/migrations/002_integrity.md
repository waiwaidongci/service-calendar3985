# 迁移 002：报告自检、修复与可追溯复核

## 背景
历史报告缺少自检，结果被误改后仍可能被复核与定时取用。本次引入冻结底稿校验、
结果版本化、原子修复切换、复核撤销/重核、交付门禁与事件流水。

## 结构变更
- `sla_runs` 新增列：`health`、`health_detail`、`result_version`、`checked_at`、
  `repaired_at`、`repair_seq`。
- `delivery_schedules` 新增列：`auto_paused`（区分修复自动暂停与人工停用）。
- `deliveries` 新增列：`result_version`、`corrected`、`superseded_by_run_version`。
- 新表：
  - `run_result_versions`：每次结果版本（initial/repair）固化结果与两份校验和；
  - `run_repair_jobs`：修复任务，含幂等键 `idem_key`、状态与尝试次数；
  - `run_events`：同 run 内 `seq` 严格递增的事件流水，作为先后次序凭据；
  - `run_reviews`：复核记录，修复切换后旧记录置 `revoked`。
- 新表由 `Base.metadata.create_all` 创建；旧表缺列由 `src/config/migrate.py`
  以 `ADD COLUMN` 幂等补齐（PostgreSQL 用 `IF NOT EXISTS`，SQLite 逐列探测）。

## 数据回填
- 历史报告补 `result_version=1`、`repair_seq=0`；已完成报告回填 v1 结果版本，
  并按冻结底稿做一次基线自检，写入首条 `run.history` 事件。
- 历史交付补 `result_version=1`、`corrected=False`；历史计划补 `auto_paused=False`。

## 执行
应用与 worker 启动时自动调用 `run_migrations()`，幂等可重复执行；
已有数据库升级前仍建议先备份。
