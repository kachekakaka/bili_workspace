# 运行数据目录

`userdata/` 是本机和 Docker 的持久化运行数据根目录。Git 只跟踪本说明和 `.gitkeep`，其余内容均由程序生成并被忽略。

典型内容包括：

```text
bili_workspace.db          SQLite 主数据库
bili_workspace.db-wal      SQLite WAL（运行时可能存在）
bili_workspace.db-shm      SQLite 共享内存文件（运行时可能存在）
indexes/                    作品库与设备导出下载索引
task_logs/                  每个下载任务的详细日志
cache/                      封面、兼容播放副本和运行缓存
tmp/                        下载、混流、转码和设备导出临时文件
export_runtime.json         设备导出运行配置
```

任务、分组、标签关系、删除记录、管理员、会话、观看进度和任务快照均通过 SQLite 或本目录下的运行文件持久化。旧版本位于 `config/` 的数据库，以及位于 `downloads/` 的索引和任务日志，会在安全条件满足时迁移到这里。

Windows/便携运行时默认使用仓库根目录的 `userdata/`。Docker 中映射为 `/data/userdata`，应与 `/data/config` 和 `/downloads` 分别挂载。

备份时至少保留整个 `userdata/`。复制正在运行的 SQLite 数据库前应先停止应用，或使用支持 SQLite 一致性快照的备份方式。`cache/` 与 `tmp/` 可重建，但保留整个目录最不容易遗漏任务状态、索引或日志。
