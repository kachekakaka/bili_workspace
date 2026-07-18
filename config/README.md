# 运行配置目录

Git 只跟踪模板：

```text
config.json.default
runtime.env.default
```

运行时自动生成、且不会提交到 GitHub：

```text
config.json
runtime.env
bili_workspace.db
bili_workspace.db-wal
bili_workspace.db-shm
bbdown/BBDown.data
```

启动、`setup.bat`、`start.bat`、`update.bat` 和 Docker 入口都会同步模板：

- 文件不存在时复制模板；
- 文件存在时保留原值；
- JSON 模板新增字段时递归补入缺失字段；
- ENV 模板新增键时追加缺失键；
- 自定义字段不会被删除；
- JSON 原子写入并保留 `.bak`；
- 损坏配置不会被模板静默覆盖。

Docker 中整个目录对应 `/data/config`，应映射到 QNAP 宿主机并纳入备份。管理员、会话、任务、逻辑分组、作品库和观看进度均保存在该目录的 SQLite 数据库中。
