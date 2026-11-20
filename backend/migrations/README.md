# Schema 版本

## v1（初始）
由 SQLAlchemy 模型在启动时经 `Base.metadata.create_all` 创建。本地小型应用不执行破坏性迁移；修改 schema 前请备份具名数据卷 `db-data`。

## v2（留白外溢，增量）
新增三张表，均为只增不改写，`create_all` 会在已有库上自动补建，不影响 v1 表与历史运行：

| 表 | 模型 | 用途 |
|---|---|---|
| `spillover_submissions` | `SpilloverSubmission` | 三份资料（roster/edges/clicks）并发补交的同一批次容器；`status` open→sealed，封存后不可改写 |
| `spillover_corrections` | `SpilloverCorrection` | 联系/点击更正独立封存（自带 SHA256）；已封存批次的更正标记 `rejected_sealed`，不并入封存依据 |
| `spillover_runs` | `SpilloverRun` | 留白外溢运行；快照与 checksum 独立冻结，重跑读取同一封存快照，checksum 不变 |

升级方式：沿用 `docker compose up -d --build`，应用启动自动建表；旧卷数据保留。
回退方式：停用新版本后，三张新表可保留不动，旧版本代码不引用它们；如需彻底回退再手工 `DROP TABLE spillover_runs, spillover_corrections, spillover_submissions;`。
