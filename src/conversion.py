"""Local-only conversion and atomic, collision-safe output publication."""
from __future__ import annotations

import os
import tempfile
import zipfile
import json
import hashlib
from pathlib import Path

SUPPORTED = {'.pdf', '.docx', '.pptx', '.xlsx', '.xls', '.html', '.htm',
             '.csv', '.json', '.txt', '.md', '.xml', '.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp', '.epub', '.doc', '.ppt'}


class UserError(Exception):
    pass


def make_converter():
    from markitdown import MarkItDown
    from markitdown.converters import (PlainTextConverter, HtmlConverter,
        DocxConverter, PptxConverter, XlsxConverter, XlsConverter, PdfConverter,
        CsvConverter, EpubConverter)
    converter = MarkItDown(enable_builtins=False, enable_plugins=False)
    # Only offline document converters are registered, never URL/cloud/audio ones.
    converter.register_converter(PlainTextConverter(), priority=10)
    converter.register_converter(HtmlConverter(), priority=10)
    from office_details import SeparatedPptxConverter
    for cls in (DocxConverter, SeparatedPptxConverter, XlsxConverter, XlsConverter,
                PdfConverter, CsvConverter, EpubConverter):
        converter.register_converter(cls())
    from math_pdf import MathPdfConverter
    converter.register_converter(MathPdfConverter())
    return converter


def validate_source(path: Path):
    ext = path.suffix.lower()
    if ext in {'.doc','.ppt'}:
        raise UserError('旧版 DOC/PPT 尚未集成经过离线安全验证的本地转换器。本机即使安装 Office 也不会自动调用；请在 Office 中另存为 DOCX/PPTX 后再添加。不会通过改扩展名转换。')
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


def convert_one(converter, source: Path, folder: Path, options=None):
    validate_source(source)
    from local_ocr import IMAGE_EXTENSIONS, ocr_image, convert_pdf_with_ocr
    options=options or {}
    progress=options.get('_progress',lambda message:None)
    progress('检查原文件并提取内容')
    with source.open('rb') as stream:initial_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    ocr_pages=[]
    office_facts={}
    if source.suffix.lower()=='.docx':
        from office_details import docx_with_math
        text,office_facts=docx_with_math(source)
    elif source.suffix.lower() in IMAGE_EXTENSIONS:
        text=ocr_image(source)['text']
        ocr_pages=[1]
    else:
        text=None
        if source.suffix.lower()=='.pdf':text,ocr_pages=convert_pdf_with_ocr(converter,source,options)
        if text is None:text=converter.convert_local(str(source),keep_data_uris=True).text_content
        if source.suffix.lower()=='.xlsx':
            from office_details import excel_details
            text+=excel_details(source)
    if not text or not text.strip():
        raise UserError('未提取到可用文字。文件可能为空白、文字无法识别或受保护；请核对原文及 OCR 设置。')
    from quality import diagnose, report_path, publish_report
    progress('提取完成，正在生成质量诊断')
    report = diagnose(source, text)
    report.update(office_facts)
    if office_facts.get('omml_objects'):
        report['issues'].append(f'检测并逐项处理 {office_facts["omml_objects"]} 个原生 OMML 公式；不支持的公式编号：{office_facts["omml_failed"]}。计数不证明公式语义正确。')
    if ocr_pages:
        report['ocr_pages']=ocr_pages
        report['status']='review';report['label']='已保存 · OCR 需要核对'
        report['issues'].insert(0,f'使用 Windows 本地 OCR 的页码：{ocr_pages}。普通 OCR 不保证数学公式、表格结构正确；图片输入目前只处理首帧。')
    from assets import Assets, export_assets
    assets=Assets(folder,progress)
    try:
        text=export_assets(source,text,assets)
        with source.open('rb') as stream:final_hash=hashlib.file_digest(stream,'sha256').hexdigest()
        if initial_hash!=final_hash or report['source_sha256']!=initial_hash:
            raise UserError('转换期间原文件发生变化，未发布结果。请关闭正在编辑该文件的程序后重试。')
    except Exception:
        assets.cleanup()
        raise
    report['assets']=assets.files
    if not assets.files:assets.cleanup()
    report['issues']=[x for x in report['issues'] if '本阶段尚未导出 PDF 插图' not in x and '当前未保证资产完整导出' not in x]
    report['issues']+=assets.warnings
    report['output_characters']=len(text)
    if report['issues'] and not ocr_pages:
        report['status']='review';report['label']='已保存 · 需要核对'
    if source.suffix.lower()=='.pdf':report['issues'].append('附有逐页原图用于核对复杂公式和结构，原图不是已识别的 LaTeX；图片对象单独导出，矢量插图保留在页面核对图中。')
    try:
        progress('诊断和资产导出完成，正在提交结果')
        target = save_atomic(folder, source.stem, text)
    except Exception:
        assets.cleanup();raise
    try:
        publish_report(target,report)
    except Exception:
        target.unlink(missing_ok=True)
        assets.cleanup()
        raise
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
