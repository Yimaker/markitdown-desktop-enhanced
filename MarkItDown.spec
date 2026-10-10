# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata, collect_dynamic_libs

root = Path(SPECPATH)
data = [(str(root / 'src' / 'app.ico'), '.')]
for package in ['magika', 'mammoth', 'markitdown', 'onnxruntime', 'tzdata']:
    data += collect_data_files(package)
for package in ['markitdown', 'magika', 'mammoth', 'pandas', 'openpyxl', 'xlrd', 'pdfminer.six', 'pdfplumber']:
    data += copy_metadata(package)
hidden = collect_submodules('markitdown') + collect_submodules('mammoth') + collect_submodules('magika')
hidden += ['pandas.io.excel._openpyxl', 'pandas.io.excel._xlrd', 'onnxruntime.capi.onnxruntime_pybind11_state', 'verification']
a = Analysis([str(root / 'src' / 'launcher.py')], pathex=[str(root / 'src')],
    binaries=collect_dynamic_libs('onnxruntime'), datas=data, hiddenimports=hidden,
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
              'tkinter', 'matplotlib', 'scipy',
              'IPython', 'pytest', 'pandas.tests', 'numpy.tests'],
    noarchive=False)
# Qt on current Windows uses the OS ICU API. A PATH-provided Poppler ICU DLL
# has version-suffixed exports and is incompatible with that API. Do not bundle
# these OS DLL names from unrelated runtime directories. Windows 10/11 also
# supplies UCRT/API-set DLLs; PATH copies from media tools must not shadow them.
a.binaries = [item for item in a.binaries if Path(item[0]).name.lower()
              not in {'icuuc.dll', 'icudt78.dll', 'ucrtbase.dll'}
              and not Path(item[0]).name.lower().startswith('api-ms-')]
# Installation provenance can contain private build-machine paths.
a.datas = [item for item in a.datas if Path(item[0]).name.lower() != 'direct_url.json']
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MarkItDown-Enhanced',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    runtime_tmpdir=None, console=False, disable_windowed_traceback=False,
    icon=str(root / 'src' / 'app.ico'))

