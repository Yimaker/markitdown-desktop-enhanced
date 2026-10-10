from __future__ import annotations
import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QUrl, QByteArray, QPointF, QMargins, QTimer
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QTabWidget, QTabBar, QTextBrowser, QPlainTextEdit,
    QComboBox, QApplication)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView

from conversion import make_converter, validate_source, friendly_error
from ui_common import label, ElideLabel, button, tool, document_icon

MAX_PREVIEW = 180000


class SafeMarkdown(QTextBrowser):
    """Render local text only; never fetch resources or follow document links."""
    def __init__(self):
        super().__init__()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setAcceptDrops(False)
        self.blocked_resources = []
        self.document().setDefaultStyleSheet('''
            body { color: #ededed; font-family: "Microsoft YaHei UI"; }
            h1 { font-size: 24px; } h2 { font-size: 20px; } h3 { font-size: 17px; }
            p, li { line-height: 1.6; } table { border-collapse: collapse; }
            td, th { border: 1px solid #555555; padding: 6px; }
            a { color: #b8d4ff; } pre { white-space: pre-wrap; }
        ''')

    def loadResource(self, resource_type, url):
        self.blocked_resources.append(url.toString())
        return QByteArray()


class PreviewWorker(QThread):
    loaded = Signal(str, str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            if self.path.suffix.lower() in {'.md','.txt','.json','.csv','.xml'}:
                data = self.path.read_bytes()
                try:
                    text = data.decode('utf-8-sig')
                except UnicodeDecodeError:
                    from charset_normalizer import from_bytes
                    result = from_bytes(data).best()
                    if result is None:
                        raise ValueError('Unknown encoding')
                    text = str(result)
            else:
                validate_source(self.path)
                text = make_converter().convert_local(str(self.path)).text_content
            self.loaded.emit(text, '')
        except Exception as exc:
            logging.exception('Preview failed: %s', self.path)
            self.loaded.emit('', friendly_error(exc))


class PreviewTab(QWidget):
    expand_requested = Signal()
    notify = Signal(str)

    def __init__(self, path: Path, text: str | None = None, extracted=False):
        super().__init__()
        self.setObjectName('viewerContent')
        self.path = Path(path)
        self.text = ''
        self.worker = None
        self.extracted = extracted
        self.pdf_document = None
        self.pdf_view = None
        self.ready = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(16,12,12,12)
        bar.setSpacing(6)
        self.title = ElideLabel(self.path.name, 'fileName')
        self.title.setToolTip(str(self.path))
        bar.addWidget(self.title,1)
        self.zoom = QComboBox()
        self.zoom.addItems(['适合宽度','65%','80%','100%','125%','150%'])
        self.zoom.setFixedWidth(103)
        self.zoom.setAccessibleName('PDF 缩放')
        self.zoom.currentIndexChanged.connect(self.change_zoom)
        self.zoom.setVisible(self.path.suffix.lower()=='.pdf')
        bar.addWidget(self.zoom)
        self.raw_btn = button('原文',self.toggle_raw,name='subtle')
        self.raw_btn.setCheckable(True)
        self.raw_btn.setEnabled(False)
        self.raw_btn.setVisible(self.path.suffix.lower()!='.pdf')
        bar.addWidget(self.raw_btn)
        self.copy_btn = tool('copy','复制全文',self.copy_text)
        self.copy_btn.setEnabled(False)
        bar.addWidget(self.copy_btn)
        bar.addWidget(tool('external','用系统应用打开',self.open_external))
        bar.addWidget(tool('expand','扩展 / 返回对话',self.expand_requested.emit))
        layout.addLayout(bar)
        rule = QFrame()
        rule.setObjectName('rule')
        layout.addWidget(rule)
        self.stack = QStackedWidget()
        empty = QWidget()
        ev = QVBoxLayout(empty)
        ev.setContentsMargins(32,30,32,30)
        ev.addStretch()
        self.message_title = label('正在读取文件…','fileName')
        self.message_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(self.message_title)
        self.message_body = label('内容将在这里显示。','muted')
        self.message_body.setWordWrap(True)
        self.message_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(self.message_body)
        ev.addStretch()
        self.stack.addWidget(empty)
        self.reader = SafeMarkdown()
        self.reader.anchorClicked.connect(lambda _: self.notify.emit('预览中的链接不会自动打开，可复制后自行使用。'))
        self.reader.setAccessibleName('文件阅读预览')
        self.stack.addWidget(self.reader)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setAcceptDrops(False)
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.raw.setAccessibleName('文件纯文本原文')
        self.stack.addWidget(self.raw)
        layout.addWidget(self.stack,1)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(16,9,12,9)
        self.note = ElideLabel('本地预览','small')
        bottom.addWidget(self.note,1)
        self.previous = tool('back','上一页',lambda:self.jump_page(-1),28)
        self.next = tool('next','下一页',lambda:self.jump_page(1),28)
        self.page_label = label('','small')
        for w in [self.previous,self.page_label,self.next]:
            w.setVisible(self.path.suffix.lower()=='.pdf')
            bottom.addWidget(w)
        layout.addLayout(bottom)
        if self.path.suffix.lower()=='.pdf':
            self.load_pdf()
        elif text is not None:
            self.loaded(text,'')
        else:
            self.worker = PreviewWorker(self.path)
            self.worker.loaded.connect(self.loaded)
            self.worker.finished.connect(self.worker_finished)
            self.worker.start()

    def load_pdf(self):
        self.pdf_view = QPdfView(self)
        # Keep the document alive throughout the view's destruction.
        self.pdf_document = QPdfDocument(self.pdf_view)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.pdf_view.setDocumentMargins(QMargins(24,24,24,24))
        self.pdf_view.setPageSpacing(20)
        self.pdf_view.setStyleSheet('QPdfView { background: #181818; border: none; }')
        self.pdf_view.setDocument(self.pdf_document)
        self.stack.addWidget(self.pdf_view)
        self.pdf_document.statusChanged.connect(self.pdf_status)
        self.pdf_view.pageNavigator().currentPageChanged.connect(self.update_page)
        self.pdf_document.load(str(self.path))
        self.pdf_status(self.pdf_document.status())

    def pdf_status(self,status):
        if status==QPdfDocument.Status.Ready:
            self.stack.setCurrentWidget(self.pdf_view)
            self.ready = True
            self.copy_btn.setEnabled(True)
            self.copy_btn.setToolTip('复制本页文字')
            self.copy_btn.setAccessibleName('复制本页文字')
            self.note.set_full('原 PDF 预览 · 保留原页面排版')
            self.update_page(0)
        elif status==QPdfDocument.Status.Error:
            self.message_title.setText('这个 PDF 无法预览')
            self.message_body.setText('文件可能已损坏或被加密。可以用系统应用打开检查。')
            self.stack.setCurrentIndex(0)

    def update_page(self,*_):
        if not self.pdf_document:
            return
        count = self.pdf_document.pageCount()
        page = self.pdf_view.pageNavigator().currentPage()
        self.page_label.setText(f'{page+1} / {count}')
        self.previous.setEnabled(page>0)
        self.next.setEnabled(page<count-1)

    def jump_page(self, delta):
        if self.pdf_document and self.ready:
            navigator = self.pdf_view.pageNavigator()
            page = max(0,min(self.pdf_document.pageCount()-1,navigator.currentPage()+delta))
            navigator.jump(page,QPointF(0,0))

    def change_zoom(self,index):
        if not self.pdf_view:
            return
        if index==0:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        else:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor([.65,.8,1,1.25,1.5][index-1])

    def loaded(self,text,error):
        if error:
            self.message_title.setText('暂时无法读取这个文件')
            self.message_body.setText(error)
            return
        self.text = text
        self.ready = True
        visible = text[:MAX_PREVIEW]
        self.raw.setPlainText(visible)
        # Plain text and structured data remain literal; Markdown/Office gets a reader.
        is_markdown = self.path.suffix.lower()=='.md' or self.extracted or self.path.suffix.lower() in {'.docx','.pptx','.xlsx','.xls','.html','.htm'}
        if is_markdown:
            self.reader.setMarkdown(visible)
            self.stack.setCurrentWidget(self.reader)
        else:
            self.reader.setPlainText(visible)
            self.stack.setCurrentWidget(self.reader)
        self.copy_btn.setEnabled(True)
        self.raw_btn.setEnabled(True)
        if self.path.suffix.lower()=='.md':
            # Preserve the file's actual line breaks on first open. The optional
            # reading view remains available, including for imperfect PDF output.
            self.raw_btn.setChecked(True)
            self.raw_btn.setText('阅读')
            self.stack.setCurrentWidget(self.raw)
        kind = '提取文本预览' if self.extracted or self.path.suffix.lower() in {'.docx','.pptx','.xlsx','.xls','.html','.htm'} else '文件内容'
        self.note.set_full(f'{kind} · {len(text):,} 字符' + (' · 预览前 18 万字符，复制全文不受影响' if len(text)>MAX_PREVIEW else ''))
        self.note.setToolTip(str(self.path))

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        worker.deleteLater()

    def toggle_raw(self):
        if self.ready and not self.pdf_document:
            self.stack.setCurrentWidget(self.raw if self.raw_btn.isChecked() else self.reader)
            self.raw_btn.setText('阅读' if self.raw_btn.isChecked() else '原文')

    def copy_text(self):
        if self.pdf_document:
            page = self.pdf_view.pageNavigator().currentPage()
            text = self.pdf_document.getAllText(page).text()
            QApplication.clipboard().setText(text)
            self.notify.emit(f'已复制第 {page+1} 页的文字。')
        elif self.ready:
            QApplication.clipboard().setText(self.text)
            self.notify.emit(f'已复制 {len(self.text):,} 个字符。')

    def open_external(self):
        if not self.path.is_file():
            self.notify.emit('文件已移动或删除，请重新选择。')
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path))):
            self.notify.emit('系统没有关联这个格式，请从文件夹中选择应用打开。')


class ViewerPanel(QFrame):
    count_changed = Signal(int)
    expand_requested = Signal()
    notify = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('viewer')
        self.setMinimumWidth(410)
        self.keys = {}
        self.retired = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideMiddle)
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.addStretch()
        t=label('文件预览','fileName')
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(t)
        t=label('点击对话中的原文件或完成文件，\n即可从这里打开。','muted')
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(t)
        ev.addStretch()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tabs)
        layout.addWidget(self.stack)

    def open_file(self,key,path,text=None,extracted=False):
        if key in self.keys:
            tab = self.keys[key]
            self.tabs.setCurrentWidget(tab)
            return tab
        tab = PreviewTab(Path(path),text,extracted)
        tab.expand_requested.connect(self.expand_requested.emit)
        tab.notify.connect(self.notify.emit)
        i=self.tabs.addTab(tab,document_icon(Path(path).suffix,18),Path(path).name)
        self.tabs.setTabToolTip(i,str(path))
        close = tool('close','关闭这个文件预览',lambda:self.close_widget(tab),24)
        self.tabs.tabBar().setTabButton(i,QTabBar.ButtonPosition.RightSide,close)
        self.keys[key]=tab
        self.tabs.setCurrentIndex(i)
        self.stack.setCurrentIndex(1)
        # Cached elision must be measured after the tab receives its real width.
        QTimer.singleShot(0,tab.title,tab.title.redraw)
        self.count_changed.emit(self.tabs.count())
        return tab

    def close_widget(self,tab):
        index=self.tabs.indexOf(tab)
        if index<0:
            return
        self.tabs.removeTab(index)
        if tab.pdf_view is not None:
            tab.pdf_view.setDocument(None)
            tab.pdf_document.close()
        self.keys={k:v for k,v in self.keys.items() if v is not tab}
        if tab.worker and tab.worker.isRunning():
            self.retired.append(tab)
            tab.worker.finished.connect(lambda:self.retire_finished(tab))
        else:
            tab.deleteLater()
        if self.tabs.count()==0:
            self.stack.setCurrentIndex(0)
        self.count_changed.emit(self.tabs.count())

    def retire_finished(self,tab):
        if tab in self.retired:
            self.retired.remove(tab)
        tab.deleteLater()

    def clear(self):
        while self.tabs.count():
            self.close_widget(self.tabs.widget(0))

    def has_jobs(self):
        return any(t.worker and t.worker.isRunning() for t in list(self.keys.values())+self.retired)
