"""Geometry-based extraction for selectable mathematical PDFs.

Uses glyph baselines/font sizes for scripts and actual drawn rules for tables.
It does not infer missing mathematical content or use OCR/network services.
"""
from __future__ import annotations
import collections
import re
import statistics
import unicodedata
from dataclasses import dataclass

import pdfplumber
from markitdown import DocumentConverter,DocumentConverterResult

LATEX={
    'ℕ':r'\mathbb{N}', 'ℤ':r'\mathbb{Z}', 'ℚ':r'\mathbb{Q}', 'ℝ':r'\mathbb{R}',
    'ε':r'\varepsilon ', 'ι':r'\iota ', 'α':r'\alpha ', 'β':r'\beta ',
    'γ':r'\gamma ', 'δ':r'\delta ', 'θ':r'\theta ', 'λ':r'\lambda ',
    'π':r'\pi ', 'σ':r'\sigma ', 'φ':r'\varphi ', 'ω':r'\omega ',
    '∀':r'\forall ', '∃':r'\exists ', '∈':r'\in ', '∉':r'\notin ',
    '≤':r'\le ', '≥':r'\ge ', '≠':r'\ne ', '≈':r'\approx ',
    '⟺':r'\Longleftrightarrow ', '⇔':r'\Longleftrightarrow ',
    '⇒':r'\Rightarrow ', '→':r'\to ', '⊆':r'\subseteq ', '⊂':r'\subset ',
    '∞':r'\infty ', '…':r'\ldots ', '⋯':r'\cdots ',
    '~':r'\sim ', '≁':r'\nsim ',
    '·':r'\cdot ', '×':r'\times ', '−':'-', '⁄':'/',
    '{':r'\{', '}':r'\}', '|':r'\vert ', '′':"'", '″':"''",
}

def math_char(c):
    return c.get('virtual',False) or c.get('_math_detected',False) or bool(re.search(r'math|cmmi|cmsy|cmex|stix|euler|symbol',c.get('fontname',''),re.I)) or any(0x1d400<=ord(ch)<=0x1d7ff or 0x2200<=ord(ch)<=0x22ff for ch in c['text'])

def mark_geometric_scripts(chars):
    """A smaller raised/lowered neighbour is evidence even in ordinary fonts.

    This remains a candidate transcription; footnotes can resemble exponents.
    """
    grid=collections.defaultdict(list)
    for b in chars:
        if re.fullmatch(r'[A-Za-z0-9)]',b['text']):
            grid[(int(b['x1']//24),int(baseline(b)//24))].append(b)
    radius=min(4,max(1,int(max((c['size'] for c in chars),default=12)/24)+1))
    for c in chars:
        if not c['text'].strip():continue
        x=int(c['x0']//24);y=int(baseline(c)//24)
        nearby=(b for dx in range(-radius,radius+1) for dy in range(-radius,radius+1) for b in grid.get((x+dx,y+dy),()))
        candidates=[b for b in nearby if b is not c and
                    c['size']<b['size']*.82 and -.3*b['size']<=c['x0']-b['x1']<=b['size']*.6 and
                    b['size']*.14<abs(baseline(c)-baseline(b))<b['size']*.85]
        if candidates:
            b=min(candidates,key=lambda b:abs(c['x0']-b['x1'])+abs(baseline(c)-baseline(b)))
            # A superscript after a prose word is usually a footnote, not x^2.
            bx=int(b['x0']//24);by=int(baseline(b)//24)
            prior=(p for dx in (-1,0,1) for dy in (-1,0,1) for p in grid.get((bx+dx,by+dy),()))
            if b['text'].isalpha() and any(p is not b and p['text'].isalpha() and -.1*b['size']<=b['x0']-p['x1']<.15*b['size'] and abs(baseline(b)-baseline(p))<.12*b['size'] for p in prior):
                continue
            b['_math_detected']=True;c['_math_detected']=True

def glyph_tex(text):
    return ''.join(LATEX.get(ch,LATEX.get(unicodedata.normalize('NFKC',ch),unicodedata.normalize('NFKC',ch))) for ch in text)

def baseline(c):
    return c.get('baseline',c.get('matrix',(0,0,0,0,0,-c['bottom']))[5])

def center_y(c):return (c['top']+c['bottom'])/2

def mode_size(chars):
    return collections.Counter(round(c['size'],2) for c in chars if c['text'].strip()).most_common(1)[0][0] if chars else 11.5

@dataclass
class Block:
    kind:str
    text:str
    page:int
    top:float
    bottom:float
    x0:float=0
    x1:float=0
    header:tuple=()
    rows:list|None=None


def attach_scripts(chars):
    """Attach small raised/lowered glyphs to their actual left-side base."""
    if not chars:return []
    if all(c.get('_attached') for c in chars):return sorted(chars,key=lambda c:c['x0'])
    size=max((c['size'] for c in chars if not c['text'].isspace()),default=11.5)
    bases=[dict(c,sub=[],sup=[],_attached=True) for c in chars if c['size']>=size*.82 or c.get('virtual')]
    small=[c for c in chars if c['size']<size*.82 and not c.get('virtual')]
    unresolved=[]
    groups=[]
    for c in sorted(small,key=lambda c:(-baseline(c),c['x0'])):
        group=next((g for g in groups if abs(baseline(g[0])-baseline(c))<.8 and -.5<=c['x0']-max(s['x1'] for s in g)<=c['size']*.65),None)
        if group is None:groups.append([c])
        else:group.append(c)
    for group in sorted(groups,key=lambda g:g[0]['x0']):
        c=min(group,key=lambda c:c['x0'])
        candidates=[]
        for b in bases:
            gap=c['x0']-b['x1']
            dy=baseline(c)-baseline(b)
            if b['text'].strip() and math_char(b) and -.5*size<=gap<=size*.95 and c['x0']>=b['x0']+.35*(b['x1']-b['x0']) and abs(dy)<size*1.5:
                if dy>size*.14 or dy<-size*.10:
                    candidates.append((abs(gap)+.3*abs(dy),b,'sup' if dy>0 else 'sub'))
        if candidates:
            _,b,role=min(candidates,key=lambda t:t[0])
            b[role].extend(group)
        else:
            unresolved.extend(dict(c,sub=[],sup=[],_attached=True) for c in group)
    result=bases+unresolved
    return sorted(result,key=lambda c:c['x0'])

def pure_tex(chars):
    out=[]
    for c in attach_scripts(chars):
        part=c['text'] if c.get('virtual') else glyph_tex(c['text'])
        if c['sub']:part+='_{'+''.join(glyph_tex(s['text']) for s in sorted(c['sub'],key=lambda s:s['x0']))+'}'
        if c['sup']:part+='^{'+''.join(glyph_tex(s['text']) for s in sorted(c['sup'],key=lambda s:s['x0']))+'}'
        out.append(part)
    text=''.join(out).strip()
    text=re.sub(r'(?<![A-Za-z\\])max(?![A-Za-z])',r'\\max ',text)
    return text

def replace_fractions(page,chars,regions=None):
    chars=list(chars)
    base=mode_size(chars)
    bars=[]
    for r in page.rects+page.lines:
        if r['height']<=1.3 and 3<=r['width']<=page.width*.4:
            y=(r['top']+r['bottom'])/2
            x0,x1=r['x0'],r['x1']
            # Numerators and denominators must contain actual mathematical glyphs.
            num=[c for c in chars if math_char(c) and x0-.8<=(c['x0']+c['x1'])/2<=x1+.8 and y-base*1.75<center_y(c)<y-base*.1]
            den=[c for c in chars if math_char(c) and x0-.8<=(c['x0']+c['x1'])/2<=x1+.8 and y+base*.1<center_y(c)<y+base*1.75]
            if num and den:
                bars.append((r,num,den))
    consumed=set()
    virtual=[]
    for r,num,den in sorted(bars,key=lambda t:t[0]['width']):
        involved=num+den
        if any(id(c) in consumed for c in involved):continue
        consumed.update(id(c) for c in involved)
        size=mode_size(involved)
        y=(r['top']+r['bottom'])/2
        virtual.append({'text':r'\frac{'+pure_tex(num)+'}{'+pure_tex(den)+'}',
            'x0':r['x0'],'x1':r['x1'],'top':y-size*.55,'bottom':y+size*.45,
            'size':size,'baseline':page.height-y-size*.28125,
            'fontname':'MathVirtual','virtual':True})
    return [c for c in chars if id(c) not in consumed]+virtual

def replace_arrow_labels(chars):
    consumed=set();result=[]
    arrows=[c for c in chars if c['text'] in {'→','⟶'}]
    for arrow in arrows:
        labels=[c for c in chars if c is not arrow and math_char(c) and c['size']<=arrow['size'] and
            c['text'].isalpha() and arrow['x0']-3<=(c['x0']+c['x1'])/2<=arrow['x1']+3 and
            arrow['size']*.1<baseline(c)-baseline(arrow)<arrow['size']*1.6]
        if labels:
            consumed.update(id(c) for c in labels+[arrow])
            result.append(dict(arrow,text=r'\xrightarrow{'+''.join(glyph_tex(c['text']) for c in sorted(labels,key=lambda c:c['x0']))+'}',virtual=True))
    return [c for c in chars if id(c) not in consumed]+result

def line_groups(chars):
    if not chars:return []
    base=max(c['size'] for c in chars) if len(chars)<60 else mode_size(chars)
    anchors=[c for c in chars if c['size']>=base*.82 or c.get('virtual')]
    small=[c for c in chars if c not in anchors]
    lines=[]
    for c in sorted(anchors,key=lambda c:-baseline(c)):
        found=next((l for l in lines if abs(baseline(c)-l['y'])<1.5),None)
        if found is None:
            found={'y':baseline(c),'chars':[]}
            lines.append(found)
        found['chars'].append(c)
    for c in small:
        choices=[]
        for l in lines:
            delta=abs(baseline(c)-l['y'])
            left=min(b['x0'] for b in l['chars'])
            right=max(b['x1'] for b in l['chars'])
            if delta<base*.85 and left-base<=c['x0']<=right+base:
                choices.append((delta,l))
        if choices:
            min(choices,key=lambda t:t[0])[1]['chars'].append(c)
        else:
            lines.append({'y':baseline(c),'chars':[c]})
    return sorted(lines,key=lambda l:-l['y'])

def render_line(chars):
    tokens=attach_scripts(chars)
    fragments=[]
    current=[]
    math=False
    last=None
    def flush():
        if not current:return
        if math:
            s=pure_tex(current)
            if s:fragments.append('$'+s+'$')
        else:fragments.append(''.join(c['text'] for c in current))
        current.clear()
    for c in tokens:
        cmath=math_char(c)
        # Spaces between adjacent math glyphs belong inside the formula.
        if c['text'].isspace() and current and math:cmath=True
        if current and cmath!=math:flush()
        math=cmath
        if not math and last and not last['text'].isspace() and not c['text'].isspace():
            gap=c['x0']-last['x1']
            if gap>max(1.5,c['size']*.25):current.append(dict(c,text=' '))
        current.append(c)
        last=c
    flush()
    text=''.join(fragments).strip().replace('$$','')
    # Each scripted base was already annotated by attach_scripts; render its
    # script-bearing token without losing attachments on the second grouping.
    return text

def rule_tables(page):
    """Only real narrow border rectangles/lines participate in table finding."""
    vertical=[];horizontal=[]
    for r in page.rects+page.lines:
        if r['width']<=1.3 and r['height']>=1.5:
            x=(r['x0']+r['x1'])/2
            vertical.append({'object_type':'line','orientation':'v','x0':x,'x1':x,'top':r['top'],'bottom':r['bottom'],'height':r['height'],'width':0})
        elif r['height']<=1.3 and r['width']>=12:
            y=(r['top']+r['bottom'])/2
            horizontal.append({'object_type':'line','orientation':'h','x0':r['x0'],'x1':r['x1'],'top':y,'bottom':y,'width':r['width'],'height':0})
    if len(vertical)<3 or len(horizontal)<3:return []
    tables=page.find_tables({'vertical_strategy':'explicit','horizontal_strategy':'explicit',
        'explicit_vertical_lines':vertical,'explicit_horizontal_lines':horizontal,
        'snap_tolerance':1.5,'join_tolerance':2,'intersection_tolerance':2})
    return [t for t in tables if len(t.columns)>=2 and len(t.rows)>=2 and t.bbox[2]-t.bbox[0]>page.width*.25]

def table_block(page,table,number):
    rows=[]
    for row in table.rows:
        cells=[]
        for cell in row.cells:
            if cell is None:cells.append('');continue
            x0,top,x1,bottom=cell
            chars=[c for c in page.chars if x0<=(c['x0']+c['x1'])/2<x1 and top<=center_y(c)<bottom]
            chars=replace_arrow_labels(replace_fractions(page,chars))
            cells.append(' '.join(render_line(l['chars']) for l in line_groups(chars)).replace('|',r'\|'))
        rows.append(cells)
    header=tuple(rows[0])
    return Block('table','',number,table.bbox[1],table.bbox[3],table.bbox[0],table.bbox[2],header,rows[1:])

def extract_math_pdf(stream):
    blocks=[];math_count=0;script_count=0
    with pdfplumber.open(stream) as doc:
        for page in doc.pages:
            mark_geometric_scripts(page.chars)
            math_count+=sum(math_char(c) for c in page.chars)
            page.close()
        # Conservative routing avoids changing existing ordinary-document behavior.
        if math_count==0:return None
        # Remove only repeated edge lines observed on multiple distinct pages.
        # A one-off edge paragraph must survive regardless of its position.
        edge_lines=[]
        repeated=collections.Counter()
        for page in doc.pages:
            found=[]
            for line in line_groups(page.chars):
                cs=line['chars']
                if not cs:continue
                y=sum(center_y(c) for c in cs)/len(cs)
                if y<page.height*.055 or y>page.height*.945:
                    value=''.join(c['text'] for c in sorted(cs,key=lambda c:c['x0'])).strip()
                    key=(re.sub(r'\d+','#',value),round(y/page.height,2))
                    # Digits alone or labelled page counts are accepted only when repeated.
                    found.append((key,min(c['top'] for c in cs),max(c['bottom'] for c in cs)))
            edge_lines.append(found)
            repeated.update(set(x[0] for x in found))
            page.close()
        threshold=max(2, int(len(doc.pages)*.6+.999))
        for number,page in enumerate(doc.pages,1):
            mark_geometric_scripts(page.chars)
            tables=rule_tables(page)
            exclusions=[t.bbox for t in tables]
            edge_ranges=[(top,bottom) for key,top,bottom in edge_lines[number-1] if repeated[key]>=threshold]
            chars=[c for c in page.chars if not any(top<=center_y(c)<=bottom for top,bottom in edge_ranges) and not any(x0<=(c['x0']+c['x1'])/2<=x1 and top<=center_y(c)<=bottom for x0,top,x1,bottom in exclusions)]
            script_count+=sum(math_char(c) and c['size']<mode_size(chars)*.82 for c in chars)
            chars=replace_arrow_labels(replace_fractions(page,chars))
            pageblocks=[table_block(page,t,number) for t in tables]
            for l in line_groups(chars):
                cs=l['chars'];text=render_line(cs)
                if not text:continue
                plain=''.join(c['text'] for c in sorted(cs,key=lambda c:c['x0'])).strip()
                size=max(c['size'] for c in cs)
                x0=min(c['x0'] for c in cs);x1=max(c['x1'] for c in cs)
                top=min(c['top'] for c in cs);bottom=max(c['bottom'] for c in cs)
                if re.match(r'^问题\s*\d+',plain):kind='h2'
                elif re.match(r'^\d+\.\d+\s',plain):kind='h3'
                elif plain in {'项目总结','参考资料'}:kind='h2'
                elif size>=20:kind='h1'
                elif all(math_char(c) or c['text'].isspace() for c in cs) and x1-x0<page.width*.9:kind='math'
                else:kind='body'
                if kind=='math':text=pure_tex(cs)
                # Right-edge occupancy, in a scale-independent page measure.
                pageblocks.append(Block(kind,text,number,top,bottom,x0,x1/page.width))
            blocks.extend(sorted(pageblocks,key=lambda b:b.top))
            page.close()
    merged=[]
    for b in blocks:
        if (b.kind=='body' and merged and merged[-1].kind=='body' and not re.match(r'^\[\d+\]|^表\s*\d+',b.text) and
            merged[-1].x1>=.83 and
            (b.page==merged[-1].page and b.top-merged[-1].bottom<15)):
            previous=merged[-1]
            separator=' ' if re.search(r'[A-Za-z0-9]$',previous.text) and re.match(r'[A-Za-z0-9]',b.text) else ''
            previous.text=(previous.text+separator+b.text).replace('$$','')
            previous.page=b.page;previous.bottom=b.bottom;previous.x1=b.x1
        else:merged.append(b)
    out=[]
    previous_page=None
    for b in merged:
        if b.page!=previous_page:
            out.append(f'<!-- source-page: {b.page} -->')
            previous_page=b.page
        if b.kind.startswith('h'):out.append('#'*int(b.kind[1])+' '+b.text)
        elif b.kind=='math':out.append('$$\n'+b.text+'\n$$')
        elif b.kind=='table':
            out.append('| '+' | '.join(b.header)+' |\n| '+' | '.join('---' for _ in b.header)+' |\n'+'\n'.join('| '+' | '.join(r)+' |' for r in b.rows))
        else:out.append(b.text)
    return '\n\n'.join(out)+'\n'

class MathPdfConverter(DocumentConverter):
    def accepts(self,file_stream,stream_info,**kwargs):
        return (stream_info.extension or '').lower() in {'.pdf','pdf'} or (stream_info.mimetype or '').startswith('application/pdf')
    def convert(self,file_stream,stream_info,**kwargs):
        position=file_stream.tell()
        try:
            text=extract_math_pdf(file_stream)
        finally:
            file_stream.seek(position)
        if text is None:
            from markitdown.converters import PdfConverter
            return PdfConverter().convert(file_stream,stream_info,**kwargs)
        return DocumentConverterResult(markdown=text)
