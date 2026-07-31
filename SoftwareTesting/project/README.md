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

Windows 使用仓库集成 Python、BBDown 和 FFmpeg；源码环境需要项目锁定的开发依赖。T-PROJECT 不执行 T-DOC，完整测试应按协议另行运行文档门禁。缺少运行时、Node 或依赖且尚未进入检查阶段时为 `blocked`；进入检查阶段后的非零退出为 `failed`；中断或运行器异常时为 `inconclusive`。

测试不得访问真实持久化目录或凭据。进程与清理约束见[测试安全](../SAFETY.md)。
