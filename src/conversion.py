"""Local-only conversion and atomic, collision-safe output publication."""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

SUPPORTED = {'.pdf', '.docx', '.pptx', '.xlsx', '.xls', '.html', '.htm',
             '.csv', '.json', '.txt', '.md', '.xml'}


class UserError(Exception):
    pass


def make_converter():
    from markitdown import MarkItDown
    from markitdown.converters import (PlainTextConverter, HtmlConverter,
        DocxConverter, PptxConverter, XlsxConverter, XlsConverter, PdfConverter,
        CsvConverter)
    converter = MarkItDown(enable_builtins=False, enable_plugins=False)
    # Only offline document converters are registered, never URL/cloud/audio ones.
    converter.register_converter(PlainTextConverter(), priority=10)
    converter.register_converter(HtmlConverter(), priority=10)
    for cls in (DocxConverter, PptxConverter, XlsxConverter, XlsConverter,
                PdfConverter, CsvConverter):
        converter.register_converter(cls())
    from math_pdf import MathPdfConverter
    converter.register_converter(MathPdfConverter())
    return converter


def validate_source(path: Path):
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise UserError('暂不支持这个格式。请选择 PDF、Word、PPT、Excel 或文本文件。')
    if not path.is_file():
        raise UserError('原文件已移动或删除，请重新添加。')
    if path.stat().st_size == 0:
        raise UserError('文件是空的，请检查原文件后重试。')
    with path.open('rb') as stream:
        header = stream.read(1024)
    if ext == '.pdf' and b'%PDF-' not in header:
        raise UserError('PDF 文件已损坏或格式不正确，请确认原文件能正常打开。')
    if ext == '.xls' and not header.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        raise UserError('XLS 文件格式不正确，请在 Excel 中另存为 XLSX 后重试。')
    required = {'.docx': 'word/document.xml', '.pptx': 'ppt/presentation.xml',
                '.xlsx': 'xl/workbook.xml'}
    if ext in required:
        try:
            with zipfile.ZipFile(path) as z:
                if required[ext] not in z.namelist():
                    raise UserError('文件内容与扩展名不符，请重新保存原文件。')
        except zipfile.BadZipFile:
            raise UserError('文件已损坏或被加密，请打开原文件检查后重试。') from None


def save_atomic(folder: Path, stem: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    # Keep room for a suffix within Windows' per-component length limit.
    stem = stem[:150].rstrip(' .') or '转换结果'
    fd, temporary = tempfile.mkstemp(prefix='.markitdown-', suffix='.tmp', dir=folder)
    temp = Path(temporary)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        for i in range(100000):
            final = folder / (f'{stem}.md' if i == 0 else f'{stem} ({i + 1}).md')
            if os.name == 'nt':
                try:
                    # Windows rename fails if the target exists; never replace it.
                    os.rename(temp, final)
                    return final
                except FileExistsError:
                    continue
            else:
                try:
                    os.link(temp, final)
                    temp.unlink()
                    return final
                except FileExistsError:
                    continue
        raise UserError('同名结果过多，请选择其他保存位置。')
    finally:
        temp.unlink(missing_ok=True)


def convert_one(converter, source: Path, folder: Path):
    validate_source(source)
    result = converter.convert_local(str(source))
    text = result.text_content
    if not text or not text.strip():
        raise UserError('未提取到可用文字。扫描版 PDF 需要先做 OCR，再重新转换。')
    target = save_atomic(folder, source.stem, text)
    return target, text


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, UserError):
        return str(exc)
    if isinstance(exc, PermissionError):
        return '无法读取文件或写入保存位置。请关闭占用程序，或换一个可写入的文件夹。'
    if isinstance(exc, FileNotFoundError):
        return '找不到原文件或保存位置，请重新选择。'
    if isinstance(exc, OSError):
        return '读取或保存失败，请检查磁盘空间、文件路径和文件夹权限。'
    return '无法解析这个文件。请确认原文件能打开；加密文件请先解除密码，或重新另存后再试。'
