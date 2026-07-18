# 运行配置目录

`config/` 只保存配置、标签定义和 Bilibili 登录凭据，不再承载 SQLite 或任务运行数据。

Git 只跟踪模板：

```text
config.json.default
runtime.env.default
tags.json.default
README.md
```

运行时自动生成、且不会提交到 GitHub：

```text
config.json
runtime.env
tags.json
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

数据库、任务快照、下载索引、任务日志、缓存和临时文件位于同级 `userdata/`；永久媒体文件只写入 `downloads/`。

Docker 中本目录映射到 `/data/config`，应与 `/data/userdata` 和 `/downloads` 分别持久化。`bbdown/BBDown.data` 含登录凭据，备份时必须加密并限制访问。
