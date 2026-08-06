# T-PROJECT 项目完整自检

- Registry ID：`T-PROJECT`
- 执行类别：`full`
- 工作目录：仓库根目录
- 输入：当前候选源码、仓库集成运行资产和隔离测试数据
- 唯一职责：执行项目现有源码边界、Python、Ruff、pytest、前端模块以及集成运行资产自检入口

Windows 规范命令：

```bat
set "BILI_VERIFY_REQUIRE_NODE=1"
verify.bat
```

Linux/macOS 源码环境规范命令：

```bash
sh scripts/dev/verify-source.sh
```

两个入口都会先在仓库外测试根创建带所有权标记的独立 run-id 目录，将全部运行资产和临时输出重定向到该目录，并默认保留。Windows 使用隔离解压的仓库集成 Python、BBDown 和 FFmpeg；源码环境需要项目锁定的开发依赖。每次运行的日志和 `results/result.json` 位于命令最后显示的绝对路径中。

T-PROJECT 不执行 T-DOC，完整测试应按协议另行运行文档门禁。缺少运行时、Node 或依赖且尚未进入检查阶段时为 `blocked`；进入检查阶段后的非零退出为 `failed`；中断或运行器异常时为 `inconclusive`。测试根可通过 `BILI_TEST_ROOT` 覆盖，但必须满足[测试安全](../SAFETY.md)中的外部路径与所有权规则。

测试不得访问真实持久化目录或凭据，也不会自动清理运行目录。进程与清理约束见[测试安全](../SAFETY.md)。
