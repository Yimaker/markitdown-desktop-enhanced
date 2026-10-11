"""Office structure supplements and per-equation OMML failure isolation."""
import io
import zipfile
import uuid
from collections import Counter
from markitdown.converters import PptxConverter


class SeparatedPptxConverter(PptxConverter):
    """Keep following slide text outside a chart or table's final row."""

    def _convert_chart_to_markdown(self, chart):
        return super()._convert_chart_to_markdown(chart).rstrip() + '\n\n'

    def _convert_table_to_markdown(self, table, **kwargs):
        return super()._convert_table_to_markdown(table, **kwargs).rstrip() + '\n\n'

def docx_with_math(source):
    from lxml import etree
    from markitdown.converter_utils.docx.math.omml import oMath2Latex
    from markitdown.converters import DocxConverter
    from markitdown import StreamInfo
    M='http://schemas.openxmlformats.org/officeDocument/2006/math'
    W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    count=0;failed=[];math_payloads={}
    # Only authenticated OMML objects bypass prose escaping. No dollar-text
    # detection or global unescaping: literal prose/code remains untouched.
    token_prefix='OMML'+uuid.uuid4().hex.upper()+'TOKEN'
    style_map=[];title_root=False
    stream=io.BytesIO()
    with zipfile.ZipFile(source) as original,zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as output:
        parser=etree.XMLParser(resolve_entities=False,no_network=True)
        main=etree.fromstring(original.read('word/document.xml'),parser)
        if 'word/styles.xml' in original.namelist():
            styles=etree.fromstring(original.read('word/styles.xml'),parser)
            names={s.get('{'+W+'}styleId'):s.find('{'+W+'}name').get('{'+W+'}val')
                   for s in styles.findall('{'+W+'}style') if s.find('{'+W+'}name') is not None}
            body=main.find('{'+W+'}body')
            meaningful=[p for p in body if ''.join(p.itertext()).strip()]
            def style_name(p):
                node=p.find('{'+W+'}pPr/{'+W+'}pStyle')
                return names.get(node.get('{'+W+'}val'),'') if node is not None else ''
            titles=[p for p in meaningful if p.tag=='{'+W+'}p' and style_name(p).lower()=='title']
            used=[style_name(p).lower() for p in main.iter('{'+W+'}p')]
            # A single leading semantic Title can be the document root. Do not
            # collapse Heading6, infer levels from font size, or reorder headings.
            title_root=len(titles)==1 and meaningful[0] is titles[0] and 'heading 6' not in used
            for name in set(names.values()):
                lower=name.lower()
                if lower=='title':level=1
                elif title_root and lower in {f'heading {n}' for n in range(1,6)}:level=int(lower[-1])+1
                else:continue
                style_map.append(f"p[style-name='{name}'] => h{level}:fresh")
        for item in original.infolist():
            data=original.read(item.filename)
            if item.filename in {'word/document.xml','word/footnotes.xml','word/endnotes.xml'}:
                root=etree.fromstring(data,etree.XMLParser(resolve_entities=False,no_network=True))
                for eq in list(root.iter('{'+M+'}oMath')):
                    count+=1
                    for fraction in eq.iter('{'+M+'}f'):
                        if fraction.find('{'+M+'}fPr') is None:
                            fraction.insert(0,etree.Element('{'+M+'}fPr'))
                    try:
                        latex=oMath2Latex(eq).latex
                        if not latex.strip():raise ValueError('Empty math conversion')
                        display=eq.getparent().tag=='{'+M+'}oMathPara'
                        delimiter='$$' if display else '$'
                        payload=(delimiter+'\n'+latex+'\n'+delimiter) if display else delimiter+latex+delimiter
                        value=token_prefix+str(count)+'END'
                        math_payloads[value]=payload
                    except Exception:
                        failed.append(count)
                        value=f'[原生公式 {count} 未能可靠转换，请对照原 Word]'
                    run=etree.Element('{'+W+'}r');text=etree.SubElement(run,'{'+W+'}t');text.text=value
                    eq.getparent().replace(eq,run)
                for para in list(root.iter('{'+M+'}oMathPara')):
                    parent=para.getparent();index=parent.index(para)
                    runs=[child for child in para if child.tag=='{'+W+'}r']
                    if parent.tag=='{'+W+'}p':
                        for run in runs:parent.insert(index,run);index+=1
                    else:
                        wrapper=etree.Element('{'+W+'}p')
                        for run in runs:wrapper.append(run)
                        parent.insert(index,wrapper)
                    parent.remove(para)
                data=etree.tostring(root,xml_declaration=True,encoding='UTF-8')
            output.writestr(item,data)
    stream.seek(0)
    text=DocxConverter().convert(stream,StreamInfo(extension='.docx'),keep_data_uris=True,style_map='\n'.join(style_map)).text_content
    for token,payload in math_payloads.items():
        if text.count(token)!=1:
            raise ValueError('DOCX math placeholder was lost or duplicated during conversion')
        text=text.replace(token,payload)
    return text,{'omml_objects':count,'omml_failed':failed,'docx_title_root':title_root}

def excel_details(source):
    import openpyxl
    formulas=openpyxl.load_workbook(source,data_only=False,keep_links=False)
    cached=openpyxl.load_workbook(source,data_only=True,read_only=True,keep_links=False)
    lines=['\n\n## Excel 公式与结构说明','Markdown 只保存文字，不能计算公式，也不保留交互、完整格式或实时外部链接。缓存值可能过期；本工具不重新计算。']
    def escape(value):return str(value).replace('|',r'\|').replace('\n','<br>')
    try:
        for sheet in formulas:
            lines.append(f'\n### 工作表：{sheet.title}\n')
            if sheet.sheet_state!='visible':lines.append('原工作表状态：'+sheet.sheet_state)
            if sheet.merged_cells.ranges:lines.append('合并区域（值位于左上角，Markdown 表格不能复现合并）：'+', '.join(map(str,sheet.merged_cells.ranges)))
            if sheet.freeze_panes:lines.append('原冻结位置：'+str(sheet.freeze_panes))
            formats=Counter()
            rows=[]
            for row in sheet:
                for cell in row:
                    if cell.value is not None and cell.number_format!='General':formats[cell.number_format]+=1
                    if cell.data_type=='f':
                        formula=cell.value if isinstance(cell.value,str) else getattr(cell.value,'text',str(cell.value))
                        value=cached[sheet.title][cell.coordinate].value
                        rows.append(f'| {cell.coordinate} | {escape(formula)} | {escape(value) if value is not None else "无已保存缓存值"} |')
            if formats:lines.append('原数字格式及使用单元格数：'+ '; '.join(f'{key} ({n})' for key,n in formats.items()))
            if rows:lines.extend(['| 单元格 | 原公式 | 文件中缓存值（非重新计算） |','| --- | --- | --- |',*rows])
    finally:formulas.close();cached.close()
    return '\n\n'.join(lines)
