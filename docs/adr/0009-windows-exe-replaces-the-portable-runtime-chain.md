# Windows EXE 替代旧便携运行链

Windows 启动器验收后，项目选择唯一的 Windows 运行入口，不再并行维护 `start.bat`、便携 Python、BBDown／FFmpeg packs 及其构建和验证链。保留双轨会产生两套资源准备、运行边界和用户说明，因此旧链的必要验证职责已迁移到源码或启动器测试，而不是随旧资产一并保留。
