# Windows 启动器离线内置 BBDown 与 FFmpeg

Windows 启动器内置固定版本且具有来源与摘要记录的 BBDown 和 FFmpeg，使用时不从网络获取，以换取离线可用和工具身份确定；代价是 EXE 体积增大。Bilibili 会话凭据仍由数据根拥有，不进入 EXE 或控制根。若体积无法继续由普通 Git 单文件承载，必须重新决定分发方式，不能静默改为在线下载。
