# Chuni-Eventer v0.4.3

## 修复（打包版 quicktex / PNG→DDS）

- 打包后 **不再**在进程内直接跑 quicktex 编码（易整体闪退）。
- 子进程改为：`ChuniEventer.exe --chuni-quicktex-worker <in> <out> <q> <mip>`，在 `run_desktop.py` 入口**先于 Qt** 转交 `quicktex_worker`，避免误启动主界面，并与开发版 `-m quicktex_worker` 一样具备进程隔离。
