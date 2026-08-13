# T-PROJECT 项目完整自检

- Registry ID：`T-PROJECT`
- 执行类别：`full`
- 工作目录：仓库根目录
- 输入：当前候选源码、既有兼容浏览器和隔离测试数据
- 唯一职责：执行项目现有源码边界、Python、Ruff、pytest、Node 和 Playwright 自检入口

## 受管路径与阶段

| 阶段 | 受管路径或入口 | 选择规则 |
| --- | --- | --- |
| 源码与 Python | `app/`、`tests/`、`tools/`、`docker/` | 源码结构、compileall、Ruff 和 `pyproject.toml` 定义的 pytest 根 |
| Node | `web/**/*.js`、`web/**/*.mjs`、`tests/frontend/*.test.mjs` | 全部脚本语法和依赖无关 Node tests |
| Playwright | `tests/` 中的 `playwright` marker | T-PROJECT full 必需阶段；runner 在前置满足后设置 `BILI_RUN_PLAYWRIGHT=1` |
Playwright 不单独登记。`.github/workflows/ci.yml` 通过内部 `scripts/dev/run-playwright-phase.sh` 执行唯一 CI 浏览器阶段；Windows EXE、内置资源与启动器 GUI 的验证由 T-LAUNCHER 承接。

## 源码环境规范命令

```bash
sh scripts/dev/verify-source.sh
```

源码入口始终要求 Node、Playwright Python 包和一个既有兼容浏览器。可以用 `BILI_PLAYWRIGHT_CHROMIUM` 指向既有 Chromium、Chrome 或 Edge；未设置时 runner 只探测已经存在的候选，不执行安装或下载。

入口会先在仓库外测试根创建带所有权标记的独立 run-id，将配置、浏览器 profile、缓存和临时输出重定向到该目录，并默认保留。源码环境需要项目锁定的开发依赖；日志和 `results/result.json` 位于命令最后显示的绝对路径中。

T-PROJECT 不执行 T-DOC，也不执行 T-DOCKER 的真实镜像构建；其中的 Docker 配置与 Python 静态／逻辑检查不能替代这两个独立测试项。完整测试应按 Registry 和协议分别选择。缺少运行时、Node、Playwright 包或可用浏览器且尚未进入检查阶段时为 `blocked`；必需阶段被跳过为 `inconclusive`；进入检查阶段后的断言、静态检查或行为失败为 `failed`；中断或运行器异常为 `inconclusive`。测试根可通过 `BILI_TEST_ROOT` 覆盖，但必须满足[测试安全](../SAFETY.md)中的外部路径与所有权规则。

测试不得访问真实持久化目录、外部网络、用户浏览器 profile 或凭据，也不会自动清理运行目录。进程、浏览器和清理约束见[测试安全](../SAFETY.md)。
