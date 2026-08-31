# bili_workspace v0.7.0

`bili_workspace` 是一个可运行在 **Windows 本机** 和 **QNAP NAS / Docker** 上的私人 Bilibili 搜索、下载、任务管理与媒体库网站。

> 仅下载、保存和播放你有权使用的内容，并遵守适用法律、平台规则与版权要求。

## 当前能力

- 管理员可按视频关键词或 UP 主名称/UID 发现作品，普通用户可按精确 UID 或主页浏览 UP 主投稿；没有可下载候选时按需顺序续页，找到即停；
- 画质预览、原子批量下载和媒体库管理；普通用户固定使用全局最低清晰度门槛并自动选择最高可用画质；
- 任务进度与日志、暂停/继续/取消/重试，以及分组、标签、在线播放和当前设备导出；
- 一个管理员和多个普通用户，任务、日志、实时事件及设备导出按所有者隔离；
- 支持 Windows 单文件启动器和 QNAP/NAS Docker 部署。

当前应用版本为 V0.7.0，数据库 schema 为 v5。完整行为与支持边界以[项目文档总入口](docs/README.md)中的需求、设计和字段契约为准。

## 主要目录

- `app/`：Python 后端；
- `web/`：浏览器前端；
- `launcher/`：Windows amd64 单文件启动器源码、固定依赖与许可材料；源码重链接与布局边界见[启动器重链接说明](launcher/RELINKING.md)；
- `app/defaults/`：Windows 启动器与 Docker 共用的只读配置模板；
- `scripts/`：[开发、构建与验证脚本入口](scripts/README.md)；
- `docs/`：当前项目文档；
- `SoftwareTesting/`：测试治理与活动测试入口。

运行数据不在仓库内。用户选择的数据根固定包含 `config/`、`userdata/`、`downloads/`；其中配置、数据库、凭据、日志、缓存和媒体都由数据根持有。

## 构建与交付

- Windows 运行入口为仓库跟踪的 `dist/bili-workspace-launcher-0.7.0.exe`。它自带 Python 3.11、BBDown 和 FFmpeg，首次启动必须选择仓库外数据根；本机模式与显式局域网服务器模式的监听及安全配置都由该 EXE 管理。
- Docker 构建与启动入口为 `docker/build-and-start.sh`；当前运维范围保留镜像构建、验证与私有离线打包，真实 QNAP 部署方案暂缓。
- 项目停止未来正式发布，不创建新的 tag、GitHub Release 或 GHCR 正式镜像；既有 V0.7.0 发布物仅作为冻结历史后备。
- 镜像打包、网络、备份、恢复、源码更新和回滚统一从[项目文档总入口](docs/README.md)进入；验证层级与测试选择从[测试治理总入口](SoftwareTesting/README.md)进入。

## 最短运行入口

Windows：

```powershell
git clone https://github.com/kachekakaka/bili_workspace.git
cd bili_workspace
.\dist\bili-workspace-launcher-0.7.0.exe
```

Docker 镜像打包、校验和离线交付按[运维入口](docs/运维/README.md)执行。真实 QNAP 目录、账号、网络和上线方式暂不在当前入口中，后续形成新方案后再补充。


## 文档与测试

- [项目文档总入口](docs/README.md)
- [测试治理总入口](SoftwareTesting/README.md)
- [安全政策](SECURITY.md)
- [第三方声明](THIRD_PARTY_NOTICES.md)

## 已知边界

- BBDown 上游已停止维护，Bilibili 接口或扫码协议变化后可能需要替换下载适配层；
- 不提供开放注册、多管理员、匿名公开分享或每用户独立 Bilibili 凭据；
- 不自动为所有作品生成 HLS/多码率版本，兼容副本按需生成；
- 当前边界和验收口径以[需求文档](docs/需求文档.md)为准。
