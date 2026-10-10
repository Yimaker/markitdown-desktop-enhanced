"""Windowed entry point with a readable diagnostic for startup failures."""
import os
import sys
import traceback
import faulthandler
from pathlib import Path

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

diagnostics = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MarkItDown'
diagnostics.mkdir(parents=True, exist_ok=True)
native_log = open(diagnostics / 'native-crash.log', 'w', encoding='utf-8')
faulthandler.enable(file=native_log, all_threads=True)

try:
    from app import main
    code = main()
except Exception:
    text = traceback.format_exc()
    folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MarkItDown'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'startup-error.log').write_text(text, encoding='utf-8')
    if getattr(sys, 'frozen', False):
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,
            '程序未能启动。请重新下载或解压便携包。\n\n错误记录：' + str(folder / 'startup-error.log'),
            'MarkItDown', 0x10)
    else:
        sys.stderr.write(text)
    code = 1
sys.exit(code)
