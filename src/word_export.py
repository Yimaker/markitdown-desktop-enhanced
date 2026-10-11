"""Offline Pandoc AST -> editable DOCX. Input files are never rewritten."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit
import zipfile
from lxml import etree as ET
from PIL import Image
from conversion import UserError, validate_source
from quality import publish_report, report_path

FORMAT='markdown+tex_math_dollars-tex_math_single_backslash-tex_math_double_backslash-raw_tex-latex_macros-smart-yaml_metadata_block-pandoc_title_block-mmd_title_block'
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'm':'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}
W='{'+NS['w']+'}'

def resources():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'resources'

def pandoc(args, data=None, cwd=None):
    exe=resources()/'pandoc/pandoc.exe'
    if not exe.is_file():raise UserError('缺少随程序提供的 Pandoc 组件，请重新解压完整发布包。')
    try:
        p=subprocess.run([str(exe),*args],input=data,capture_output=True,cwd=cwd,
            timeout=180,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except subprocess.TimeoutExpired:
        raise UserError('Word 转换超过 180 秒，未发布结果。请拆分过大的文档后重试。') from None
    if p.returncode:raise UserError('Pandoc 转换失败：'+p.stderr.decode('utf-8',errors='replace')[:1800])
    return p.stdout,p.stderr.decode('utf-8',errors='replace').strip()

def walk(value):
    if isinstance(value,dict):
        if 't' in value:yield value
        for v in value.values():yield from walk(v)
    elif isinstance(value,list):
        for v in value:yield from walk(v)

def inline_text(items):
    return ''.join(n['c'] if n['t']=='Str' else ' ' if n['t'] in ('Space','SoftBreak','LineBreak') else '' for n in walk(items))

def filter_appendix(blocks, include):
    """Only a real level-2 header, including setext syntax, starts this appendix."""
    if include:return blocks,0
    result=[];level=None;removed=0
    for b in blocks:
        if b['t']=='Header':
            depth,_,title=b['c']
            if level is not None and depth<=level:level=None
            if depth==2 and inline_text(title).strip()=='原文资产与核对图':level=depth;removed+=1
        if level is None:result.append(b)
    return result,removed

def parse(source,include=False):
    raw=source.read_bytes()
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise UserError('Markdown 需要 UTF-8 编码，请另存为 UTF-8 后重试。') from None
    data,warnings=pandoc(['--from='+FORMAT,'--to=json'],text.encode('utf-8'),source.parent)
    ast=json.loads(data);ast['blocks'],removed=filter_appendix(ast['blocks'],include)
    # Metadata is disabled in the reader; never fetch a template or resource from it.
    ast['meta']={}
    return ast,removed,warnings,hashlib.sha256(raw).hexdigest()

def prepare_ast(ast,source,staging):
    issues=[];images=[];math=[];raw_count=0
    for node in list(walk(ast)):
        typ=node['t']
        if typ=='Math':math.append({'kind':node['c'][0]['t'],'expression':node['c'][1]})
        elif typ=='Image':
            attr,alt,target=node['c'];ref=target[0]
            # Remote, UNC, file URI and embedded-data sources are deliberately out of scope.
            decoded=unquote(ref)
            is_drive=bool(re.match(r'^[A-Za-z]:[\\/]',decoded))
            if decoded.startswith(('//','\\')) or (urlsplit(decoded).scheme and not is_drive):
                raise UserError('首版仅支持本地图片，不下载远程或 URI 图片：'+ref)
            path=Path(decoded)
            if not path.is_absolute():path=source.parent/path
            path=path.resolve()
            if not path.is_file():raise UserError('找不到本地图片：'+ref+'\n解析位置：'+str(path))
            try:
                with Image.open(path) as im:
                    im.load();w,h=im.size
                    # Snapshot into PNG avoids external relationships and unsupported codecs.
                    dest=staging/f'image-{len(images)+1}.png'
                    im.convert('RGBA' if 'A' in im.getbands() or 'transparency' in im.info else 'RGB').save(dest)
            except Exception as exc:raise UserError('无法读取本地图片：'+ref+'（'+str(exc)[:150]+'）') from None
            width=min(w/96,6.35);height=width*h/w
            if height>8:width*=8/height;height=8
            node['c'][0]=[attr[0],attr[1],[[k,v] for k,v in attr[2] if k not in ('width','height')]+[['width',f'{width:.4f}in'],['height',f'{height:.4f}in']]]
            node['c'][2]=[str(dest),target[1]]
            images.append({'source':ref,'width':w,'height':h,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        elif typ in ('RawBlock','RawInline'):
            fmt,raw=node['c'];raw_count+=1
            page=re.fullmatch(r'\s*<!--\s*source-page:\s*(\d+)\s*-->\s*',raw)
            # Preserve source-page notes, and unsupported raw markup as editable literal text.
            if typ=='RawBlock':
                literal='来源页：'+page[1] if page else raw
                node.clear();node.update({'t':'Div','c':[['',[],[['custom-style','Source Note']]], [{'t':'Para','c':[{'t':'Str','c':literal}]}]]})
            else:node.clear();node.update({'t':'Code','c':[['',[],[]],raw]})
            if not page:issues.append('原始 HTML/标记未执行，已作为原文文字保留：'+raw[:100])
    if not ast['blocks']:raise UserError('排除核对图附录后没有可转换的正文。')
    return images,math,issues

def style_docx(path):
    """Keep reusable styles; only apply structural table properties to instances."""
    with zipfile.ZipFile(path) as z:parts={n:z.read(n) for n in z.namelist()}
    root=ET.fromstring(parts['word/document.xml'])
    for table in root.findall('.//w:tbl',NS):
        pr=table.find('w:tblPr',NS)
        if pr is None:pr=ET.Element(W+'tblPr');table.insert(0,pr)
        for old in pr.findall('w:tblW',NS):pr.remove(old)
        ET.SubElement(pr,W+'tblW',{W+'w':'5000',W+'type':'pct'})
        for row in table.findall('w:tr',NS):
            for cell in row.findall('w:tc',NS):
                for p in cell.findall('w:p',NS):
                    pp=p.find('w:pPr',NS)
                    if pp is None:pp=ET.Element(W+'pPr');p.insert(0,pp)
                    st=pp.find('w:pStyle',NS)
                    if st is None:st=ET.Element(W+'pStyle');pp.insert(0,st)
                    if st.get(W+'val','') in ('','Compact','BodyText','FirstParagraph'):st.set(W+'val','TableText')
        # Header repetition; no fixed row heights, so content can grow naturally.
        first=table.find('w:tr',NS)
        if first is not None and first.find('w:trPr/w:tblHeader',NS) is not None:
            for cell in first.findall('w:tc',NS):
                cp=cell.find('w:tcPr',NS)
                if cp is None:cp=ET.Element(W+'tcPr');cell.insert(0,cp)
                ET.SubElement(cp,W+'shd',{W+'fill':'EAF0F6'})
    parts['word/document.xml']=ET.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in parts.items():z.writestr(name,content)

def inspect_docx(path,expected_images=None,expected_tables=None):
    try:
        with zipfile.ZipFile(path) as z:
            if z.testzip():raise ValueError('ZIP CRC 校验失败')
            for part in ('[Content_Types].xml','word/document.xml','word/styles.xml','word/_rels/document.xml.rels'):
                if part not in z.namelist():raise ValueError('缺少 '+part)
            for name in z.namelist():
                if name.endswith(('.xml','.rels')):ET.fromstring(z.read(name))
            root=ET.fromstring(z.read('word/document.xml'))
            rels=ET.fromstring(z.read('word/_rels/document.xml.rels'))
            byid={r.get('Id'):r for r in rels}
            blips=root.findall('.//a:blip',NS)
            for b in blips:
                rel=byid.get(b.get('{'+NS['r']+'}embed'))
                if rel is None or rel.get('TargetMode')=='External':raise ValueError('图片没有嵌入')
                target=rel.get('Target','')
                if 'word/'+target not in z.namelist():raise ValueError('缺少图片数据 '+target)
            tables=root.findall('.//w:tbl',NS)
            if expected_images is not None and len(blips)!=expected_images:raise ValueError('图片数量与源文档不一致')
            if expected_tables is not None and len(tables)!=expected_tables:raise ValueError('表格数量与源文档不一致')
            return {'omml':len(root.findall('.//m:oMath',NS)),'images':len(blips),'media':len([n for n in z.namelist() if n.startswith('word/media/')]),
                'tables':len(tables),'table_shapes':[[len(r.findall('w:tc',NS)) for r in t.findall('w:tr',NS)] for t in tables],
                'text':''.join(root.itertext())}
    except (ValueError,KeyError,zipfile.BadZipFile,ET.XMLSyntaxError) as exc:
        raise UserError('Word 完整性检查未通过，未发布结果：'+str(exc)) from None

def publish_binary(temporary,folder,stem):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    stem=stem[:150].rstrip(' .') or '转换结果'
    # Copy into destination filesystem first; then publish atomically without replacement.
    fd,raw=tempfile.mkstemp(prefix='.markitdown-word-',suffix='.tmp',dir=folder)
    tmp=Path(raw)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(Path(temporary).read_bytes());stream.flush();os.fsync(stream.fileno())
        for i in range(100000):
            final=folder/(stem+('' if i==0 else f' ({i+1})')+'.docx')
            if report_path(final).exists():continue
            try:
                if os.name=='nt':os.rename(tmp,final)
                else:os.link(tmp,final)
                return final
            except FileExistsError:continue
        raise UserError('同名结果过多，请选择其他保存位置。')
    finally:tmp.unlink(missing_ok=True)

def export_word(source,folder,options=None):
    source=Path(source).resolve();options=options or {};validate_source(source)
    if source.suffix.lower()!='.md':raise UserError('Markdown 转 Word 模式只接受 .md 文件；其他格式请切换到文档转 Markdown。')
    progress=options.get('_progress',lambda msg:None)
    progress('解析 Markdown 标题、表格与公式')
    ast,removed,parse_warning,source_hash=parse(source,options.get('include_review_appendix',False))
    with tempfile.TemporaryDirectory(prefix='markitdown-word-') as td:
        staging=Path(td);images,math,issues=prepare_ast(ast,source,staging)
        if parse_warning:issues.append(parse_warning)
        table_count=sum(n['t']=='Table' for n in walk(ast))
        out=staging/'result.docx'
        progress('嵌入本地图片并生成 Word 原生公式')
        _,warning=pandoc(['--from=json','--to=docx','--standalone','--syntax-highlighting=none',
            '--reference-doc='+str(resources()/'reference.docx'),'-o',str(out)],json.dumps(ast,ensure_ascii=False).encode('utf-8'),staging)
        if warning:issues.append('Pandoc 提示（不支持的公式保留为原始表达式）：\n'+warning)
        style_docx(out);facts=inspect_docx(out,len(images),table_count)
        if facts['omml']!=len(math):issues.append(f'识别 {len(math)} 个数学表达式，输出 {facts["omml"]} 个 OMML；请核对诊断中的原始公式清单及文中保留的原始表达式。')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=source_hash:raise UserError('转换期间 Markdown 已改变，未发布结果，请重试。')
        report={'schema':1,'direction':'md-to-docx','engine':'Pandoc 3.12.1','dialect':FORMAT,
            'source':str(source),'source_sha256':source_hash,'status':'review' if issues else 'saved',
            'label':'已生成 Word · 需要核对' if issues else '已生成 Word · 结构检查通过',
            'issues':issues,'formulas':math,'images':images,'excluded_appendices':removed,
            'structure':{k:v for k,v in facts.items() if k!='text'},
            'scope':'结构检查不等于数学语义或逐页排版检查。原始公式在 formulas 中逐项保留。'}
        progress('Word 结构检查通过，正在保存')
        final=publish_binary(out,folder,source.stem)
        try:publish_report(final,report)
        except Exception:final.unlink(missing_ok=True);raise
        return final,facts['text']
