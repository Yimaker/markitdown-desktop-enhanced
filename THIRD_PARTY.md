# 第三方组件

本项目原创界面及增强代码采用根目录 MIT 许可证。第三方代码、可执行文件、字体及模型继续遵循各自许可证，项目 MIT 不替代这些许可。

- Microsoft MarkItDown 0.1.8：上游提交 `4cc9fa1`，见 `vendor/markitdown/LICENSE` 与 `ThirdPartyNotices.md`。
- Pandoc 3.12.1：作为独立本地程序随发行 EXE 部署，由应用通过子进程调用。保留其 `COPYING.rtf`、`COPYRIGHT.txt` 与手册，见 `src/resources/pandoc/`。
  - 官方发行：https://github.com/jgm/pandoc/releases/tag/3.12.1
  - 对应源代码：https://github.com/jgm/pandoc/tree/3.12.1
  - 官方源码归档：https://github.com/jgm/pandoc/archive/refs/tags/3.12.1.tar.gz
  - 未修改 Pandoc 可执行文件；下载归档和实际内置二进制均按官方来源校验，摘要见 `src/resources/pandoc/provenance.json`。
- PySide6/Qt、PyInstaller、Python、Pillow、ziamath、ziafont、latex2mathml 及其他依赖：保留各自许可，完整资料随便携包提供。

源码 Git 仓库不保存大体积 Pandoc 可执行文件。开发者可运行 `scripts/prepare_pandoc.py` 从固定官方版本准备组件；普通用户运行发行 EXE 时不需要下载或安装 Pandoc。

作者和维护者的公开署名按第三方许可保留，不将这些公开上游联系人当作本项目使用者的私人资料。
