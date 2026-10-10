from __future__ import annotations
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton, QSizePolicy

STYLE = '''
QMainWindow, QWidget#root, QWidget#chat, QWidget#conversation { background: #181818; }
QWidget { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 14px; color: #f1f1f1; }
QLabel { background: transparent; }
QLabel#appTitle { font-size: 18px; font-weight: 600; }
QLabel#muted { color: #aaaaaa; }
QLabel#small { color: #aaaaaa; font-size: 12px; }
QLabel#emptyTitle { font-size: 25px; font-weight: 600; }
QLabel#fileName { font-size: 14px; font-weight: 600; }
QLabel#fileMeta { color: #b5b5b5; font-size: 12px; }
QPushButton, QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px 10px; color: #dfdfdf; }
QToolButton { padding: 3px; }
QPushButton:hover, QToolButton:hover { background: #303030; }
QPushButton:pressed, QToolButton:pressed { background: #383838; }
QPushButton:focus, QToolButton:focus { border: 1px solid #86ace8; }
QPushButton:disabled, QToolButton:disabled { color: #8e8e8e; background: transparent; }
QPushButton#attachment { background: #292929; border: 1px solid #353535; border-radius: 16px; padding: 0; text-align: left; }
QPushButton#attachment:hover { background: #333333; border-color: #4b4b4b; }
QPushButton#attachment:pressed { background: #363636; }
QPushButton#attachment:focus { border: 2px solid #86ace8; }
QPushButton#attachment[selected="true"] { background: #303030; border-color: #686868; }
QLabel#fileBadge { background: #171717; border-radius: 10px; }
QFrame#composer { background: #2b2b2b; border: 1px solid #3b3b3b; border-radius: 22px; }
QPushButton#send { background: #3267b4; border: 1px solid #3267b4; border-radius: 18px; color: white; padding: 0; }
QPushButton#send:hover { background: #285799; border-color: #467cc6; }
QPushButton#send:pressed { background: #224c86; }
QPushButton#send:disabled { background: #414141; border-color: #414141; }
QPushButton#send:focus { border: 2px solid #a1c3f7; }
QPushButton#subtle { font-size: 12px; color: #bcbcbc; padding: 5px 8px; }
QPushButton#retry { background: #303030; border: 1px solid #545454; border-radius: 10px; }
QFrame#viewer { background: #1c1c1c; border: none; border-left: 1px solid #353535; }
QWidget#viewerContent { background: #1c1c1c; }
QFrame#rule { background: #303030; border: none; min-height: 1px; max-height: 1px; }
QTabWidget::pane { border: none; }
QTabBar { background: #202020; }
QTabBar::tab { background: transparent; color: #b5b5b5; padding: 10px 14px; border: 1px solid transparent; border-radius: 9px; margin: 5px 2px; min-width: 95px; max-width: 210px; }
QTabBar::tab:selected { background: #2b2b2b; color: #f1f1f1; border-color: #444444; }
QTabBar::tab:hover { background: #303030; }
QTabBar::close-button { image: none; width: 14px; height: 14px; }
QPlainTextEdit, QTextBrowser { background: transparent; color: #ededed; border: none; padding: 18px 20px; selection-background-color: #365b90; selection-color: white; }
QPlainTextEdit:focus, QTextBrowser:focus { border: 1px solid #5a779d; }
QComboBox { background: #292929; border: 1px solid #404040; border-radius: 9px; padding: 6px 9px; }
QComboBox:hover { border-color: #686868; }
QComboBox QAbstractItemView { background: #292929; color: #f1f1f1; selection-background-color: #464646; border: 1px solid #555555; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 4px 1px; }
QScrollBar::handle:vertical { background: #505050; border-radius: 3px; min-height: 35px; }
QScrollBar::handle:vertical:hover { background: #686868; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: #252525; }
QSplitter::handle:hover { background: #4b4b4b; }
QProgressBar { background: #444444; border: none; border-radius: 2px; height: 3px; }
QProgressBar::chunk { background: #8baddf; border-radius: 2px; }
QToolTip { background: #333333; color: #f1f1f1; border: 1px solid #626262; padding: 6px; }
'''

PATHS = {
 'add': '<path d="M12 5v14M5 12h14"/>',
 'close': '<path d="m6 6 12 12M18 6 6 18"/>',
 'copy': '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
 'folder': '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
 'file': '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Z"/><path d="M14 3v6h6M8 13h8M8 17h6"/>',
 'send': '<path d="M12 19V5m-6 6 6-6 6 6"/>',
 'panel': '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M15 4v16"/>',
 'new': '<path d="M13 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-8M15 3l6 6M10 14l3-7 4-4 4 4-4 4-7 3Z"/>',
 'external': '<path d="M13 3h8v8M21 3l-11 11M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
 'stop': '<rect x="6" y="6" width="12" height="12" rx="1"/>',
 'back': '<path d="m14 5-7 7 7 7"/>',
 'next': '<path d="m10 5 7 7-7 7"/>',
 'expand': '<path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"/>',
 'check': '<path d="m5 12 4 4L19 6"/>',
}

def svg_icon(svg, size=20):
    renderer = QSvgRenderer(svg.encode('utf-8'))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)

def icon(name, color='#d6d6d6', size=20):
    return svg_icon(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>', size)

def document_icon(ext, size=30):
    ext = ext.lower().lstrip('.')
    color = {'pdf':'#e9575e','docx':'#5c8fd9','pptx':'#e48a5a','xlsx':'#5dac84','xls':'#5dac84'}.get(ext,'#929dac')
    kind = ext.upper()[:4]
    return svg_icon(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 36"><path fill="{color}" d="M7 1h12l8 8v23a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V4a3 3 0 0 1 3-3Z"/><path fill="#fff" fill-opacity=".45" d="M19 1v6a2 2 0 0 0 2 2h6Z"/><text x="15.5" y="27" text-anchor="middle" fill="white" font-family="Segoe UI" font-size="7" font-weight="700">{kind}</text></svg>',size)

def label(text='', name=None):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    return w

def button(text, action, glyph=None, name=None):
    w = QPushButton(text)
    if name:
        w.setObjectName(name)
    if glyph:
        w.setIcon(icon(glyph))
        w.setIconSize(QSize(18,18))
    w.clicked.connect(action)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    return w

def tool(glyph, hint, action, size=34):
    w = QToolButton()
    w.setIcon(icon(glyph))
    w.setIconSize(QSize(18,18))
    w.setFixedSize(size,size)
    w.setToolTip(hint)
    w.setAccessibleName(hint)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.clicked.connect(action)
    return w

class ElideLabel(QLabel):
    def __init__(self, text='', name=None, mode=Qt.TextElideMode.ElideMiddle):
        super().__init__()
        self.full = text
        self.mode = mode
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if name:
            self.setObjectName(name)
        self.set_full(text)

    def set_full(self, text):
        self.full = text
        self.setToolTip(text)
        self.redraw()

    def redraw(self):
        self.setText(self.fontMetrics().elidedText(self.full, self.mode, max(10,self.width()-2)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.redraw()

def readable_size(size):
    if size < 1024:
        return f'{size} B'
    if size < 1024*1024:
        return f'{size/1024:.0f} KB'
    return f'{size/1024/1024:.1f} MB'
