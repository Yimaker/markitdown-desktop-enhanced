"""Evidence-based diagnostics, never an accuracy score or semantic certification."""
import hashlib
import json
from pathlib import Path
import zipfile
import os
import tempfile
import re


def diagnose(source, text):
    source = Path(source)
    issues, pages = [], []
    ext = source.suffix.lower()
    if ext == '.pdf':
        import pdfplumber
        with pdfplumber.open(source) as doc:
            from math_pdf import math_char, mark_geometric_scripts,rule_tables
            for n, page in enumerate(doc.pages, 1):
                chars = page.chars
                mark_geometric_scripts(chars)
                count = sum(len(c['text'].strip()) for c in chars)
                images = len(page.images)
                maths = sum(math_char(c) for c in chars)
                ruled=len(rule_tables(page))
                pages.append(dict(page=n, characters=count, images=images, math_glyphs=maths,ruled_table_fragments=ruled))
                if count < 20:
                    issues.append(f'第 {n} 页仅有 {count} 个可提取非空白字符，含 {images} 个图像对象：可能为空页、扫描页或文字很少，请对照原 PDF。')
                if maths:
                    issues.append(f'第 {n} 页检测到 {maths} 个数学字体/符号字形；坐标提取不能证明上下标、分数和矩阵语义正确。')
                if images:
                    issues.append(f'第 {n} 页含 {images} 个图像对象；本阶段尚未导出 PDF 插图。')
                rows={}
                for word in page.extract_words():rows.setdefault(round(word['top']/3),[]).append(word)
                gaps=0
                for row in rows.values():
                    row=sorted(row,key=lambda w:w['x0'])
                    if any(right['x0']-left['x1']>page.width*.2 for left,right in zip(row,row[1:])):gaps+=1
                if gaps>=3:issues.append(f'第 {n} 页有 {gaps} 行包含较宽水平间隔，可能是双栏或无边框表；阅读顺序和单元格结构需对照原页图。')
                page.close()
        source_count = sum(p['characters'] for p in pages)
        output_tables=len(re.findall(r'^\|[\s:|\-]+\|\s*$',text,re.M))
        ruled_tables=sum(p['ruled_table_fragments'] for p in pages)
        if output_tables>ruled_tables:
            issues.append(f'输出含 {output_tables} 个 Markdown 表格片段，源 PDF 检测到 {ruled_tables} 个明确直线边框片段；差异可能来自无边框表或误识别，请核对。')
        output_count = len(''.join(text.split()))
        if source_count and output_count < source_count * .65:
            issues.append(f'输出非空白字符数 {output_count} 明显少于 PDF 字形字符数 {source_count}，需要检查遗漏（不是准确率）。')
        issues.append('PDF 表格边界、双栏顺序、标题和跨页段落尚未经过语义验证，请对照源文档。')
        issues.append('数学 PDF 的跨页表格和段落保守分开；同一张正式表格可能输出多个片段，请核对后再合并。')
    elif ext in {'.docx', '.pptx', '.xlsx'}:
        with zipfile.ZipFile(source) as z:
            media = [n for n in z.namelist() if '/media/' in n and not n.endswith('/')]
        if media:
            issues.append(f'源文件包含 {len(media)} 个媒体文件；请检查结果中的图片引用，当前未保证资产完整导出。')
        issues.append('Office 输出为提取内容，不是原版式复刻；请核对表格、公式及阅读顺序。')
        if ext == '.xlsx':
            issues.append('Markdown 不保留电子表格的计算能力、交互和完整格式。')
        if ext == '.pptx':
            issues.append('PPT 按形状位置提取文字、表格、图表数据和备注；动画、转场、音视频与复杂重叠形状不保留。')
    elif ext=='.xls':
        issues.append('旧版 XLS 主要提取已保存数据值；公式源表达式、合并单元格和格式不保证保留。可另存 XLSX 后使用公式与结构补充。')
    elif ext=='.epub':
        issues.append('EPUB 按书脊阅读顺序提取；复杂排版不保留，无法唯一定位的图片会在资产附录保留。远程资源不会自动加载。')
    if '\ufffd' in text or '(cid:' in text:
        issues.append('输出含替代字符或未映射字形标记，部分文字可能无法正确解码。')
    with source.open('rb') as stream:
        source_hash=hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(schema=1, status='review' if issues else 'saved',
                label='已保存 · 需要核对' if issues else '已提取并保存',
                source=str(source.resolve()), source_sha256=source_hash,
                output_characters=len(text), pages=pages, issues=issues,
                scope='诊断仅记录可观察证据；未发现提示不代表语义和结构完全正确。')


def report_path(target):
    return Path(str(target) + '.diagnostics.json')

def publish_report(target,report):
    destination=report_path(target)
    fd,name=tempfile.mkstemp(prefix='.diagnostics-',suffix='.tmp',dir=destination.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2)
            stream.flush();os.fsync(stream.fileno())
        if os.name=='nt':os.rename(temporary,destination)
        else:os.link(temporary,destination)
    finally:temporary.unlink(missing_ok=True)


def read_report(target):
    try:
        return json.loads(report_path(target).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'label': '已提取并保存 · 诊断不可用', 'issues': ['未找到质量诊断，请核对原文。']}
