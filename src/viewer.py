from __future__ import annotations
import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QUrl, QByteArray, QPointF, QMargins, QTimer
from PySide6.QtGui import QDesktopServices, QTextDocument, QPixmap, QImageReader, QImage
from PySide6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QTabWidget, QTabBar, QTextBrowser, QPlainTextEdit,
    QComboBox, QApplication, QLabel, QScrollArea, QSplitter, QLineEdit, QFileDialog)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView

from conversion import make_converter, validate_source, friendly_error
from ui_common import label, ElideLabel, button, tool, document_icon

from paged_text import PagedText,CHUNK,save_edited
MAX_PREVIEW = CHUNK


class SafeMarkdown(QTextBrowser):
    """Render local text only; never fetch resources or follow document links."""
    def __init__(self):
        super().__init__()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setAcceptDrops(False)
        self.blocked_resources = []
        self.allowed_images=set()
        self.math_images={}
        self.document().setDefaultStyleSheet('''
            body { color: #ededed; font-family: "Microsoft YaHei UI"; }
            h1 { font-size: 24px; } h2 { font-size: 20px; } h3 { font-size: 17px; }
            p, li { line-height: 1.6; } table { border-collapse: collapse; }
            td, th { border: 1px solid #555555; padding: 6px; }
            a { color: #b8d4ff; } pre { white-space: pre-wrap; }
        ''')

    def loadResource(self, resource_type, url):
        if url.toString() in self.math_images:return self.math_images[url.toString()]
        if url.isLocalFile():
            path=Path(url.toLocalFile()).resolve()
            if path in self.allowed_images and path.suffix.lower() in {'.png','.jpg','.jpeg','.bmp','.gif','.webp','.tiff'}:
                return QImage(str(path))
        self.blocked_resources.append(url.toString())
        return QByteArray()


class PreviewWorker(QThread):
    loaded = Signal(object, str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            if self.path.suffix.lower() in {'.md','.txt','.json','.csv','.xml'}:
                if self.path.stat().st_size>MAX_PREVIEW:
                    try:
                        self.loaded.emit(PagedText(self.path),'')
                        return
                    except UnicodeError:pass
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
    ready_changed=Signal()

    def __init__(self, path: Path, text: str | None = None, extracted=False):
        super().__init__()
        self.setObjectName('viewerContent')
        self.path = Path(path)
        self._text = ''
        self.paged=None;self.chunk=0;self.edits={};self.editing=False;self.dirty=False;self.changing=False
        self.worker = None
        self.math_worker = None
        self.comparison=None
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
        self.math_btn=button('公式',self.show_math,name='subtle')
        self.math_btn.setToolTip('使用本地组件渲染公式，失败时保留 LaTeX 原文')
        self.math_btn.setVisible(self.path.suffix.lower()!='.pdf')
        bar.addWidget(self.math_btn)
        self.copy_btn = tool('copy','复制全文',self.copy_text)
        self.copy_btn.setEnabled(False)
        bar.addWidget(self.copy_btn)
        bar.addWidget(tool('external','用系统应用打开',self.open_external))
        bar.addWidget(tool('expand','扩展 / 返回对话',self.expand_requested.emit))
        layout.addLayout(bar)
        rule = QFrame()
        rule.setObjectName('rule')
        layout.addWidget(rule)
        self.text_tools=QWidget()
        tools_row=QHBoxLayout(self.text_tools);tools_row.setContentsMargins(12,4,12,4)
        self.find_box=QLineEdit();self.find_box.setPlaceholderText('全文查找');self.find_box.returnPressed.connect(self.find_next)
        tools_row.addWidget(self.find_box,1)
        tools_row.addWidget(button('查找',self.find_next,name='subtle'))
        self.edit_btn=button('编辑',self.toggle_edit,name='subtle');self.edit_btn.setCheckable(True);self.edit_btn.setVisible(self.path.suffix.lower()=='.md');tools_row.addWidget(self.edit_btn)
        self.save_btn=button('另存副本',self.choose_save,name='subtle');self.save_btn.setVisible(self.path.suffix.lower()=='.md');tools_row.addWidget(self.save_btn)
        self.text_tools.setVisible(self.path.suffix.lower()!='.pdf')
        layout.addWidget(self.text_tools)
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
        from quality import read_report
        for asset in read_report(self.path).get('assets',[]):
            candidate=(self.path.parent/asset['path']).resolve()
            if candidate.is_relative_to(self.path.parent.resolve()) and candidate.parent.name.startswith('assets-'):
                self.reader.allowed_images.add(candidate)
        # A portable Markdown + assets pair need not carry the diagnostic JSON.
        # Allow only explicitly referenced sibling assets; never remote URLs or
        # arbitrary local paths. Iterate lines instead of caching a long file.
        if self.path.suffix.lower()=='.md' and self.path.is_file():
            import re
            try:
                with self.path.open(encoding='utf-8-sig',errors='replace') as markdown:
                    for line in markdown:
                        for ref in re.findall(r'!\[[^\]]*\]\((assets-[^)\r\n]+)\)',line):
                            candidate=(self.path.parent/ref).resolve()
                            if candidate.is_relative_to(self.path.parent.resolve()) and candidate.parent.name.startswith('assets-'):
                                self.reader.allowed_images.add(candidate)
            except (OSError,ValueError):
                pass
        self.reader.document().setBaseUrl(QUrl.fromLocalFile(str(self.path.parent.resolve())+'/'))
        self.reader.anchorClicked.connect(lambda _: self.notify.emit('预览中的链接不会自动打开，可复制后自行使用。'))
        self.reader.setAccessibleName('文件阅读预览')
        self.stack.addWidget(self.reader)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setAcceptDrops(False)
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.raw.setAccessibleName('文件纯文本原文')
        self.raw.textChanged.connect(self.mark_dirty)
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
        if self.path.suffix.lower() in {'.png','.jpg','.jpeg','.bmp','.tif','.tiff','.webp'}:
            self.text_tools.hide();self.math_btn.hide();self.raw_btn.hide()
            image_reader=QImageReader(str(self.path))
            size=image_reader.size()
            if size.width()>1600 or size.height()>1600:
                size.scale(1600,1600,Qt.AspectRatioMode.KeepAspectRatio)
                image_reader.setScaledSize(size)
            picture=QLabel()
            picture.setPixmap(QPixmap.fromImage(image_reader.read()))
            area=QScrollArea();area.setWidget(picture)
            self.stack.addWidget(area);self.stack.setCurrentWidget(area)
            self.ready=True
            self.note.set_full('原图片预览 · 超大图片缩放显示 · 多帧图片显示首帧')
        elif self.path.suffix.lower()=='.pdf':
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
        if self.paged:
            self.stash_edit();self.show_chunk(max(0,min(len(self.paged.offsets)-1,self.chunk+delta)))
            return
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
        if isinstance(text,str):text=text.replace('\r\n','\n').replace('\r','\n')
        if self.paged:self.paged.close()
        self.paged=text if isinstance(text,PagedText) else (PagedText.from_text(text) if len(text)>MAX_PREVIEW else None)
        self._text='' if self.paged else text
        if self.paged:
            document=self.paged
            self.destroyed.connect(lambda:document.close())
        self.ready = True
        visible = self.paged.get(0) if self.paged else text
        self.raw.setPlainText(visible)
        # Plain text and structured data remain literal; Markdown/Office gets a reader.
        is_markdown = self.path.suffix.lower()=='.md' or self.extracted or self.path.suffix.lower() in {'.docx','.pptx','.xlsx','.xls','.html','.htm','.epub'}
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
        kind = '提取文本预览' if self.extracted or self.path.suffix.lower() in {'.docx','.pptx','.xlsx','.xls','.html','.htm','.epub'} else '文件内容'
        count=self.paged.length if self.paged else len(text)
        self.note.set_full(f'{kind} · {count:,} 字符' + (' · 分段浏览可访问完整内容' if self.paged else ''))
        if self.paged:
            for widget in (self.previous,self.next,self.page_label):widget.show()
            self.update_chunk_controls()
        self.note.setToolTip(str(self.path))
        self.ready_changed.emit()

    @property
    def text(self):
        return self.paged.full_text() if self.paged else self._text

    def mark_dirty(self):
        if self.editing and not self.changing:self.dirty=True

    def stash_edit(self):
        if self.editing:self.edits[self.chunk]=self.raw.toPlainText()

    def show_chunk(self,index):
        if self.math_worker and self.math_worker.isRunning():
            self.notify.emit('公式仍在渲染，请稍后翻段。');return
        self.chunk=index
        text=self.edits.get(index,self.paged.get(index) if self.paged else self._text)
        self.changing=True
        self.raw.setPlainText(text);self.reader.math_images={};self.reader.setMarkdown(text)
        self.changing=False
        self.update_chunk_controls()
        self.note.set_full(f'分段 {self.chunk+1} · 可查找全文；点击“公式”渲染当前分段')

    def update_chunk_controls(self):
        count=len(self.paged.offsets) if self.paged else 1
        self.page_label.setText(f'分段 {self.chunk+1} / {count}')
        self.previous.setEnabled(self.chunk>0);self.next.setEnabled(self.chunk<count-1)

    def find_position(self,query,start=0):
        return self.paged.find(query,start) if self.paged else self._text.find(query,start)

    def locate_position(self,position,length=0):
        if self.math_worker and self.math_worker.isRunning():
            self.notify.emit('公式渲染中，完成后可继续定位。');return
        if self.paged:
            index,local=self.paged.locate(position)
            self.stash_edit();self.show_chunk(index)
        else:local=position
        from PySide6.QtGui import QTextCursor
        raw_text=self.raw.toPlainText()
        cursor=self.raw.textCursor();cursor.setPosition(len(raw_text[:local].encode('utf-16-le'))//2)
        if length:cursor.setPosition(len(raw_text[:local+length].encode('utf-16-le'))//2,QTextCursor.MoveMode.KeepAnchor)
        self.raw.setTextCursor(cursor);self.raw.centerCursor()
        self.raw_btn.setChecked(True);self.raw_btn.setText('阅读');self.stack.setCurrentWidget(self.raw)

    def find_next(self):
        query=self.find_box.text()
        if not query or not self.ready:return
        units=self.raw.textCursor().selectionEnd()
        local=len(self.raw.toPlainText().encode('utf-16-le')[:units*2].decode('utf-16-le',errors='ignore'))
        start=(self.paged.starts[self.chunk] if self.paged else 0)+local
        position=self.find_position(query,start)
        if position<0:position=self.find_position(query)
        if position<0:self.notify.emit('全文中未找到；查找基于原始保存结果，编辑内容请另存后再搜索。')
        else:self.locate_position(position,len(query))

    def toggle_edit(self):
        if not self.ready:return
        self.stash_edit();self.editing=self.edit_btn.isChecked()
        self.raw.setReadOnly(not self.editing)
        self.raw_btn.setChecked(True);self.raw_btn.setText('阅读');self.stack.setCurrentWidget(self.raw)
        self.note.set_full('编辑当前分段；另存副本保留原结果。关闭时未另存的编辑会保存为本地草稿。' if self.editing else '浏览模式 · 原结果未修改')

    def edited_text(self):
        self.stash_edit()
        if self.paged:return ''.join(self.edits.get(i,self.paged.get(i)) for i in range(len(self.paged.offsets)))
        return self.edits.get(0,self._text)

    def save_copy(self,folder,record_history=True):
        target=save_edited(self.path,self.edited_text(),folder,record_history)
        self.dirty=False
        self.notify.emit('已另存，原结果保留：'+str(target))
        self.note.set_full('已另存副本：'+target.name+' · 当前标签仍为原结果的编辑草稿')
        return target

    def choose_save(self):
        if not self.ready:return
        folder=QFileDialog.getExistingDirectory(self,'另存副本到文件夹（不会覆盖已有文件）',str(self.path.parent))
        if folder:
            try:self.save_copy(Path(folder))
            except Exception as exc:self.notify.emit('另存失败：'+friendly_error(exc))

    def preserve_draft(self):
        if self.comparison and not self.comparison.preserve_draft():return False
        if self.dirty:
            try:self.save_copy(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'MarkItDown'/'编辑草稿')
            except Exception as exc:
                self.notify.emit('草稿未能保存，暂不关闭：'+friendly_error(exc));return False
        return True

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        worker.deleteLater()

    def show_math(self):
        if not self.ready or self.pdf_document or (self.math_worker and self.math_worker.isRunning()):return
        from math_preview import MathRenderWorker
        self.math_btn.setEnabled(False)
        self.raw.setReadOnly(True)
        self.note.set_full('正在本地渲染公式；界面仍可操作…')
        self.math_worker=MathRenderWorker(self.raw.toPlainText())
        self.math_worker.rendered.connect(self.math_loaded)
        self.math_worker.finished.connect(self.math_finished)
        self.math_worker.start()

    def math_loaded(self,text,images,failed):
        self.reader.math_images=images
        self.reader.setMarkdown(text)
        self.raw_btn.setChecked(False);self.raw_btn.setText('原文')
        self.stack.setCurrentWidget(self.reader)
        self.note.set_full(f'离线公式阅读 · {len(images)} 个不同公式已渲染 · {failed} 处保留原文；渲染不证明转写正确')

    def math_finished(self):
        worker=self.math_worker;self.math_worker=None
        if worker:worker.deleteLater()
        self.math_btn.setEnabled(True)
        self.raw.setReadOnly(not self.editing)

    def has_jobs(self):
        return bool(self.active_workers())

    def active_workers(self):
        result=[w for w in (self.worker,self.math_worker) if w and w.isRunning()]
        if self.comparison:result+=self.comparison.active_workers()
        return result

    def add_comparison(self,path,text=None):
        if self.comparison or not self.pdf_view:return
        self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
        self.comparison=PreviewTab(path,text)
        self.comparison.notify.connect(self.notify.emit)
        self.comparison.expand_requested.connect(self.expand_requested.emit)
        self.comparison.ready_changed.connect(lambda:self.sync_comparison(self.pdf_view.pageNavigator().currentPage()))
        split=QSplitter(Qt.Orientation.Horizontal)
        self.layout().removeWidget(self.stack)
        split.addWidget(self.comparison);split.addWidget(self.stack)
        self.layout().insertWidget(3,split,1)
        split.setSizes([600,600])
        self.pdf_view.pageNavigator().currentPageChanged.connect(self.sync_comparison)
        self.sync_comparison(0)

    def sync_comparison(self,page):
        if not self.comparison:return
        from PySide6.QtGui import QTextCursor
        result=self.comparison
        if result.math_worker and result.math_worker.isRunning():
            self.note.set_full('公式渲染中，暂缓自动定位；完成后可继续翻页。');return
        marker=f'<!-- source-page: {page+1} -->'
        position=result.find_position(marker)
        exact=position>=0
        if position<0:position=result.find_position(f'### 原 PDF 第 {page+1} 页核对图')
        if position>=0:result.locate_position(position)
        self.note.set_full('并排核对 · '+('已定位对应页提取文字' if exact else '此文件仅能定位原页核对图，非正文逐段映射'))

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
            text=self.edited_text()
            QApplication.clipboard().setText(text)
            self.notify.emit(f'已复制 {len(text):,} 个字符。')

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
        if not tab.preserve_draft():return False
        index=self.tabs.indexOf(tab)
        if index<0:
            return True
        self.tabs.removeTab(index)
        if tab.pdf_view is not None:
            tab.pdf_view.setDocument(None)
            tab.pdf_document.close()
        self.keys={k:v for k,v in self.keys.items() if v is not tab}
        if tab.has_jobs():
            self.retired.append(tab)
            for worker in tab.active_workers():
                worker.requestInterruption()
                worker.finished.connect(lambda:self.retire_finished(tab))
        else:
            tab.deleteLater()
        if self.tabs.count()==0:
            self.stack.setCurrentIndex(0)
        self.count_changed.emit(self.tabs.count())
        return True

    def retire_finished(self,tab):
        if tab.has_jobs():return
        if tab in self.retired:
            self.retired.remove(tab)
        tab.deleteLater()

    def clear(self):
        while self.tabs.count():
            if not self.close_widget(self.tabs.widget(0)):break

    def has_jobs(self):
        return any(t.has_jobs() for t in list(self.keys.values())+self.retired)

