# Chuni-Eventer v0.4.2

## 修复

- **打包版 PNG→DDS（quicktex）**：此前用 `sys.executable -m quicktex_worker` 启动子进程；在 PyInstaller 下 `sys.executable` 为主程序 exe，会反复弹出新的主窗口且无法正确生成 DDS。现改为在 **frozen** 模式下于当前进程内编码（调用仍放在后台线程，不阻塞 UI）。

## 其它

- 窗口标题仍为 `Chuni Eventer v{APP_VERSION}`（本版为 v0.4.2）。
