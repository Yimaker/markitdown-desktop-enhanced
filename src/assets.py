"""Local assets and original page evidence, never invented formula content."""
import base64
import hashlib
import io
from pathlib import Path
import re
import shutil
import uuid
import zipfile

class Assets:
    def __init__(self,folder,progress=None):
        self.parent=Path(folder).resolve()
        self.root=self.parent/('assets-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True,exist_ok=False)
        self.files=[];self.warnings=[];self.hashes={}
        self.progress=progress or (lambda message:None)
    def add(self,data,suffix,label):
        digest=hashlib.sha256(data).hexdigest()
        if digest in self.hashes:return self.hashes[digest]
        name=f'{len(self.files)+1:04d}{suffix}'
        (self.root/name).write_bytes(data)
        relative=self.root.name+'/'+name
        self.files.append({'path':relative,'label':label,'sha256':digest})
        self.hashes[digest]=relative
        return relative
    def cleanup(self):
        assert self.root.resolve().parent==self.parent and self.root.name.startswith('assets-')
        shutil.rmtree(self.root,ignore_errors=True)

def export_assets(source,text,assets):
    def data_uri(match):
        suffix={'png':'.png','jpeg':'.jpg','jpg':'.jpg','gif':'.gif','bmp':'.bmp','webp':'.webp','svg+xml':'.svg','tiff':'.tiff'}.get(match[1].lower(),'.bin')
        try:return assets.add(base64.b64decode(match[2],validate=True),suffix,'内嵌图片')
        except ValueError:
            assets.warnings.append('有内嵌图片编码无效，未能导出。');return match[0]
    text=re.sub(r'data:image/([\w+.-]+);base64,([A-Za-z0-9+/=]+)',data_uri,text)
    ext=source.suffix.lower();appendix=[]
    if ext in {'.md','.html','.htm'}:
        from urllib.parse import unquote,urlsplit
        def local_image(match):
            relative=unquote(match[2])
            if urlsplit(relative).scheme or relative.startswith(assets.root.name+'/'):return match[0]
            image=(source.parent/relative).resolve()
            if image.is_relative_to(source.parent.resolve()) and image.is_file() and image.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.bmp'}:
                target=assets.add(image.read_bytes(),image.suffix,'本地引用图片')
                return f'![{match[1]}]({target})'
            assets.warnings.append('有本地图片引用缺失或超出源文档目录，未自动读取；请核对该引用。')
            return match[0]
        text=re.sub(r'!\[([^\]]*)\]\(([^)]+)\)',local_image,text)
    if ext in {'.docx','.pptx','.xlsx','.epub'}:
        epub_paths={}
        with zipfile.ZipFile(source) as z:
            for name in z.namelist():
                if ('/media/' in name or (ext=='.epub' and Path(name).suffix.lower() in {'.png','.jpg','.jpeg','.gif','.webp','.svg'})) and not name.endswith('/'):
                    relative=assets.add(z.read(name),Path(name).suffix.lower(),'Office 媒体：'+Path(name).name)
                    if ext=='.epub':epub_paths[name]=relative
                    if relative not in text:appendix.append(f'![文档媒体（原位置未确定）]({relative})')
        if ext=='.epub':
            from urllib.parse import unquote,urlsplit
            def epub_image(match):
                link=unquote(match[2])
                if urlsplit(link).scheme or link.startswith('assets-'):return match[0]
                candidates=[target for name,target in epub_paths.items() if name==link or name.endswith('/'+link.lstrip('./'))]
                if len(candidates)==1:return f'![{match[1]}]({candidates[0]})'
                assets.warnings.append('EPUB 有图片相对位置无法唯一定位，已将可提取图片保留于附录。')
                return f'[图片 {match[1]}：原位置需核对]'
            text=re.sub(r'!\[([^\]]*)\]\(([^)]+)\)',epub_image,text)
    if ext=='.pdf':
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        doc=pdfium.PdfDocument(str(source))
        try:
            for n in range(len(doc)):
                assets.progress(f'导出原页核对图与图片：第 {n+1} / {len(doc)} 页')
                page=doc[n]
                try:
                    bitmap=page.render(scale=min(1.6,2200/max(page.get_size())))
                    buffer=io.BytesIO();bitmap.to_pil().save(buffer,format='PNG');bitmap.close()
                    relative=assets.add(buffer.getvalue(),'.png',f'原 PDF 第 {n+1} 页完整核对图')
                    appendix.append(f'### 原 PDF 第 {n+1} 页核对图\n\n![第 {n+1} 页原图（公式和版式以此核对）]({relative})')
                    for i,obj in enumerate(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])):
                        try:
                            bitmap=obj.get_bitmap(render=True)
                            # Detach pixels before releasing PDFium's foreign buffer.
                            picture=bitmap.to_pil().copy()
                            bitmap.warn_on_close=False;bitmap.close()
                            buffer=io.BytesIO();picture.save(buffer,format='PNG');picture.close()
                            relative=assets.add(buffer.getvalue(),'.png',f'第 {n+1} 页图片对象 {i+1}')
                            appendix.append(f'![第 {n+1} 页图片 {i+1}]({relative})')
                        except Exception:
                            assets.warnings.append(f'第 {n+1} 页图片对象 {i+1} 无法独立导出，已保留完整页面核对图。')
                finally:page.close()
        finally:doc.close()
    if appendix:text+='\n\n## 原文资产与核对图\n\n'+'\n\n'.join(appendix)+'\n'
    return text
