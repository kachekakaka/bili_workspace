# T-PROJECT 项目完整自检

- Registry ID：`T-PROJECT`
- 执行类别：`full`
- 工作目录：仓库根目录
- 输入：当前候选源码、既有兼容浏览器和隔离测试数据
- 唯一职责：执行源码安全边界、Python、Ruff、pytest、Node 和 Playwright 自检

## 阶段

| 阶段 | 入口 | 选择规则 |
| --- | --- | --- |
| 源码与 Python | `tools/verify_source.py`、compileall、Ruff、pytest | 源码安全边界和完整非 integration Python 行为测试 |
| Node | `web/**/*.js`、`web/**/*.mjs`、`tests/frontend/*.test.mjs` | 全部脚本语法和 Node 行为测试 |
| Playwright | `pytest -m playwright` | T-PROJECT full 必需阶段；只在隔离前置满足后设置 `BILI_RUN_PLAYWRIGHT=1` |

Playwright 不单独登记。`.github/workflows/ci.yml` 的 `playwright` job 是 T-PROJECT 浏览器阶段；Windows EXE、内置资源和启动器 GUI 由 T-LAUNCHER 承接。T-PROJECT 不执行 T-DOC、T-ARCHIVE、真实 Docker 构建或启动器打包。

## 规范命令

```bash
sh scripts/dev/verify-source.sh
```

入口要求 Python 3.11、Node、项目锁定的开发依赖、Playwright Python 包和一个既有兼容浏览器。可以用 `BILI_PLAYWRIGHT_CHROMIUM` 指向既有 Chromium、Chrome 或 Edge；未设置时只探测已有候选，不安装或下载。

入口在仓库外创建带最小所有权标记的独立 run，将配置、浏览器 profile、缓存、日志和临时输出重定向到其中。每个阶段的失败诊断输出到控制台；本地入口退出时精确清理 run。CI 浏览器阶段为 Artifact 上传暂时保留同样的隔离目录，上传后由临时 runner 回收。

缺少运行时、Node、开发依赖或浏览器且尚未进入检查阶段时为 `blocked`；必需阶段被跳过为 `inconclusive`；进入检查后的断言或行为失败为 `failed`。完整语义和隔离边界见[测试协议](../PROTOCOL.md)与[测试安全](../SAFETY.md)。
