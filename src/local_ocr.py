import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from conversion import UserError

IMAGE_EXTENSIONS={'.png','.jpg','.jpeg','.bmp','.tif','.tiff','.webp'}

def ocr_image(source):
    if os.name!='nt':raise UserError('本地 OCR 需要 Windows 10/11 及已安装的 OCR 语言。')
    from PIL import Image, ImageOps
    with tempfile.TemporaryDirectory(prefix='markitdown-ocr-') as raw:
        root=Path(raw)
        with Image.open(source) as image:
            image=ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((2400,2400))
            image.save(root/'image.png')
        base=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
        script=base/'windows_ocr.ps1'
        proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),str(root/'image.png'),str(root/'result.json')],capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode or not (root/'result.json').exists():
            raise UserError('Windows 本地 OCR 未能运行。请检查系统语言的 OCR 功能是否安装；原文件未修改。')
        return json.loads((root/'result.json').read_text(encoding='utf-8'))

def parse_pages(value,count):
    pages=set()
    try:
        for part in value.replace('，',',').split(','):
            bounds=[int(x.strip()) for x in part.split('-')]
            if len(bounds)==1:pages.add(bounds[0])
            elif len(bounds)==2 and bounds[0]<=bounds[1]:pages.update(range(bounds[0],bounds[1]+1))
            else:raise ValueError()
        if not pages or min(pages)<1 or max(pages)>count:raise ValueError()
    except ValueError:raise UserError(f'OCR 页码无效。请填写 1 到 {count} 内的页码，如 1,3-5。') from None
    return pages

def convert_pdf_with_ocr(converter,source,options):
    import pdfplumber
    mode=options.get('ocr','auto')
    if mode=='off':return None,[]
    with pdfplumber.open(source) as doc:
        selected=parse_pages(options.get('pages',''),len(doc.pages)) if mode=='selected' else {i for i,p in enumerate(doc.pages,1) if len(p.chars)<20 and p.images}
    if not selected:return None,[]
    import pypdfium2 as pdfium
    text=[]
    with tempfile.TemporaryDirectory(prefix='markitdown-pages-') as raw:
        root=Path(raw)
        pdf=pdfium.PdfDocument(str(source))
        try:
            for index in range(len(pdf)):
                number=index+1
                options.get('_progress',lambda message:None)(f'处理 PDF 第 {number} / {len(pdf)} 页'+(' · 本地 OCR' if number in selected else ' · 提取文字'))
                text.append(f'\n\n<!-- source-page: {number} -->\n\n## 原文第 {number} 页\n')
                if number in selected:
                    page=pdf[index]
                    bitmap=page.render(scale=min(2,2400/max(page.get_size())))
                    bitmap.to_pil().save(root/'page.png')
                    bitmap.close();page.close()
                    result=ocr_image(root/'page.png')
                    text.append('> 本页为 Windows 本地 OCR 文字，公式、表格和识别内容需对照原图核对。\n\n'+(result['text'] or '[本页未识别到文字]'))
                else:
                    single=pdfium.PdfDocument.new()
                    single.import_pages(pdf,[index]);single.save(root/'single.pdf');single.close()
                    text.append(converter.convert_local(str(root/'single.pdf')).text_content)
        finally:pdf.close()
    return '\n\n'.join(text),sorted(selected)
