# bili_workspace

> 当前 `main` 仍是源码恢复引导树，**不是可运行的正式源码提交**。

仓库里的 `bootstrap/source.part001`～`source.part003` 是完整源码归档的分段文本。请在 GitHub 仓库的 **Actions** 页面手动运行一次：

```text
Restore complete source tree
```

该工作流会在 GitHub 服务器内完成以下操作：

1. 拼接并解码仓库内的三个源码分段；
2. 校验 gzip 归档与核心源码文件；
3. 拒绝包含 `BBDown.data` 或管理员初始化令牌的归档；
4. 用真正的 Python、前端、Docker、Windows 脚本和测试文件替换当前引导树；
5. 提交回 `main`。

在出现提交信息包含 `[source-ready]` 的新提交之前，请不要把当前仓库当作可运行版本。
