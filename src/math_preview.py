"""Offline LaTeX -> MathML -> SVG -> bitmap, without document JavaScript."""
import hashlib
import re
from functools import lru_cache
from PySide6.QtCore import QThread,Signal,QByteArray,Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer

@lru_cache(maxsize=128)
def render_formula(latex):
    if len(latex)>2500:raise ValueError('Formula too long for safe preview')
    import ziamath
    # Qt SVG uses SVG 1.x references; SVG2 symbols can silently lose glyphs.
    ziamath.config.svg2=False
    svg=ziamath.Latex(latex,size=20,color='#ededed').svg()
    renderer=QSvgRenderer(QByteArray(svg.encode('utf-8')))
    size=renderer.defaultSize()
    if not renderer.isValid() or not (0<size.width()<=3000 and 0<size.height()<=1800):
        raise ValueError('Unsupported formula layout')
    image=QImage(size*2,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);renderer.render(painter);painter.end()
    image.setDevicePixelRatio(2)
    return image

class MathRenderWorker(QThread):
    rendered=Signal(str,object,int)
    def __init__(self,text):
        super().__init__();self.text=text
    def run(self):
        images={};failed=0
        pattern=re.compile(r'\$\$(.+?)\$\$|(?<!\\)\$([^$\n]+?)(?<!\\)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]',re.S)
        def replace(match):
            nonlocal failed
            if self.isInterruptionRequested():return match[0]
            latex=next(g for g in match.groups() if g is not None)
            try:
                key='math-local:'+hashlib.sha256(latex.encode()).hexdigest()
                images[key]=render_formula(latex)
                return '!['+'公式'+']('+key+')'
            except Exception:
                failed+=1;return match[0]
        # Code remains literal, even if it contains dollar signs.
        pieces=re.split(r'(```[\s\S]*?```|`[^`\n]*`)',self.text)
        result=''.join(part if i%2 else pattern.sub(replace,part) for i,part in enumerate(pieces))
        if not self.isInterruptionRequested():self.rendered.emit(result,images,failed)
