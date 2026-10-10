from __future__ import annotations
import logging
import os
import sys
import threading
import uuid
import gc
from dataclasses import dataclass, field
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QThread, Signal, QTimer, QSettings, QStandardPaths, QUrl
from PySide6.QtGui import QFont, QIcon, QDesktopServices, QKeySequence, QShortcut, QPalette, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout,
    QHBoxLayout, QStackedWidget, QScrollArea, QSplitter, QPushButton, QFileDialog,
    QSizePolicy, QProgressBar, QToolButton)
from conversion import SUPPORTED, convert_one, make_converter, friendly_error
from ui_common import STYLE, label, ElideLabel, icon, document_icon, button, tool, readable_size
from viewer import ViewerPanel

VERSION='2.1.0'
BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))

@dataclass
class Entry:
    path: Path
    id: str=field(default_factory=lambda:uuid.uuid4().hex)
    state: str='waiting'
    text: str=''
    output: Path | None=None
    error: str=''

class ConversionWorker(QThread):
    started_item=Signal(str)
    result=Signal(str,bool,str,str,str)
    progress=Signal(int,int)
    def __init__(self,entries,folder):
        super().__init__()
        self.entries=[(e.id,e.path) for e in entries]
        self.folder=folder
        self.stop_requested=threading.Event()
    def run(self):
        converter=None
        init_error=None
        try:
            converter=make_converter()
        except Exception:
            logging.exception('Converter initialization failed')
            init_error='转换组件未能加载，请重新启动程序；若仍失败，请重新解压便携包。'
        for number,(entry_id,source) in enumerate(self.entries,1):
            if self.stop_requested.is_set():
                break
            self.started_item.emit(entry_id)
            try:
                if init_error:
                    raise RuntimeError(init_error)
                target,text=convert_one(converter,source,self.folder)
                self.result.emit(entry_id,True,str(target),text,'')
            except Exception as exc:
                logging.exception('Conversion failed: %s',source)
                self.result.emit(entry_id,False,'','',init_error or friendly_error(exc))
            self.progress.emit(number,len(self.entries))

class Attachment(QPushButton):
    def __init__(self,path,detail,action):
        super().__init__()
        self.path=Path(path)
        self.setObjectName('attachment')
        self.setProperty('selected',False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('查看文件：'+self.path.name)
        self.setToolTip(str(self.path))
        self.setMinimumWidth(235)
        self.setMaximumWidth(348)
        self.setFixedHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
        layout=QHBoxLayout(self)
        layout.setContentsMargins(10,9,14,9)
        layout.setSpacing(12)
        badge=label('','fileBadge')
        badge.setFixedSize(48,48)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(document_icon(self.path.suffix,29).pixmap(29,29))
        badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(badge)
        text=QVBoxLayout()
        text.setContentsMargins(0,0,0,0)
        text.setSpacing(5)
        self.name=ElideLabel(self.path.name,'fileName')
        self.meta=ElideLabel(detail,'fileMeta')
        for w in [self.name,self.meta]:
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text.addWidget(w)
        layout.addLayout(text,1)
        self.clicked.connect(action)
    def set_detail(self,text):
        self.meta.set_full(text)

class Exchange(QWidget):
    def __init__(self,entry,window):
        super().__init__()
        self.entry=entry
        self.window=window
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Minimum)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16)
        sent=QHBoxLayout()
        sent.setContentsMargins(0,0,0,0)
        sent.setSpacing(8)
        sent.addStretch(1)
        self.source_card=Attachment(entry.path,'',lambda:window.open_entry(entry.id,False))
        sent.addWidget(self.source_card,1)
        self.remove_btn=tool('close','移除这个文件',lambda:window.remove_entry(entry.id),26)
        sent.addWidget(self.remove_btn,0,Qt.AlignmentFlag.AlignTop)
        layout.addLayout(sent)
        self.reply=QWidget()
        rv=QVBoxLayout(self.reply)
        rv.setContentsMargins(0,0,0,0)
        rv.setSpacing(10)
        self.reply_title=label('','muted')
        self.reply_title.setStyleSheet('font-size: 13px;')
        rv.addWidget(self.reply_title)
        outputrow=QHBoxLayout()
        outputrow.setContentsMargins(0,0,0,0)
        self.result_card=Attachment(entry.path.with_suffix('.md'),'Markdown',lambda:window.open_entry(entry.id,True))
        outputrow.addWidget(self.result_card,1)
        outputrow.addStretch(1)
        rv.addLayout(outputrow)
        self.error_label=label('')
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet('color: #e6b2b4; font-size: 13px;')
        rv.addWidget(self.error_label)
        self.actions=QWidget()
        ar=QHBoxLayout(self.actions)
        ar.setContentsMargins(0,0,0,0)
        ar.setSpacing(3)
        self.copy_btn=tool('copy','复制 Markdown 全文',lambda:window.copy_entry(entry.id),28)
        self.folder_btn=tool('folder','打开结果文件夹',lambda:window.open_entry_folder(entry.id),28)
        self.retry_btn=button('重试这个文件',lambda:window.retry_entry(entry.id),name='subtle')
        ar.addWidget(self.copy_btn)
        ar.addWidget(self.folder_btn)
        ar.addWidget(self.retry_btn)
        ar.addStretch()
        rv.addWidget(self.actions)
        layout.addWidget(self.reply)
        self.refresh()
    def refresh(self):
        e=self.entry
        try:
            size=readable_size(e.path.stat().st_size)
        except OSError:
            size='文件不可用'
        state={'waiting':'等待转换','running':'正在转换…','success':'已处理','failed':'转换失败'}[e.state]
        self.source_card.set_detail(f'{e.path.suffix[1:].upper()} · {size} · {state}')
        self.remove_btn.setEnabled(not self.window.busy)
        self.reply.setVisible(e.state!='waiting')
        self.result_card.setVisible(e.state=='success')
        self.error_label.setVisible(e.state=='failed')
        self.actions.setVisible(e.state in {'success','failed'})
        self.copy_btn.setVisible(e.state=='success')
        self.folder_btn.setVisible(e.state=='success')
        self.retry_btn.setVisible(e.state=='failed')
        self.retry_btn.setEnabled(not self.window.busy)
        if e.state=='running':
            self.reply_title.setText('正在提取文档内容…')
        elif e.state=='failed':
            self.reply_title.setText('这个文件没有转换成功')
            self.error_label.setText(e.error)
        elif e.state=='success':
            self.reply_title.setText('转换完成')
            self.result_card.path=e.output
            self.result_card.name.set_full(e.output.name)
            self.result_card.setToolTip(str(e.output))
            self.result_card.setAccessibleName('查看完成文件：'+e.output.name)
            self.result_card.set_detail(f'Markdown · {len(e.text):,} 字符')

class MainWindow(QMainWindow):
    batch_finished=Signal()
    def __init__(self,test_mode=False):
        super().__init__()
        self.entries=[]
        self.exchanges={}
        self.worker=None
        self.busy=False
        self.closing=False
        self.expanded=False
        self.test_mode=test_mode
        self.settings=QSettings('MarkItDownLocal','Desktop')
        documents=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        default=str(Path(documents)/'MarkItDown 转换结果')
        self.folder=Path(default if test_mode else self.settings.value('output',default))
        self.setWindowTitle('MarkItDown · 文档转换')
        self.setWindowIcon(QIcon(str(BASE/'app.ico')))
        self.setMinimumSize(900,650)
        self.resize(1180,800)
        self.setAcceptDrops(True)
        self.build_ui()
        self.update_controls()
        QShortcut(QKeySequence('Ctrl+O'),self,activated=self.choose_files)
        QShortcut(QKeySequence('Ctrl+Return'),self,activated=self.start_conversion)
        QShortcut(QKeySequence('Escape'),self,activated=self.close_viewer)

    def build_ui(self):
        root=QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        layout=QVBoxLayout(root)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        header=QHBoxLayout()
        header.setContentsMargins(24,13,20,13)
        header.setSpacing(9)
        header.addWidget(label('MarkItDown','appTitle'))
        header.addWidget(label('文档转换','small'))
        header.addStretch()
        self.clear_btn=tool('new','新建转换 / 清空文件记录',self.clear_queue,36)
        header.addWidget(self.clear_btn)
        self.panel_btn=QToolButton()
        self.panel_btn.setIcon(icon('panel'))
        self.panel_btn.setIconSize(QSize(19,19))
        self.panel_btn.setText('0')
        self.panel_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.panel_btn.setFixedHeight(36)
        self.panel_btn.setMinimumWidth(55)
        self.panel_btn.setToolTip('打开文件预览')
        self.panel_btn.setAccessibleName('展开或收起文件预览')
        self.panel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.panel_btn.clicked.connect(self.toggle_viewer)
        header.addWidget(self.panel_btn)
        layout.addLayout(header)
        self.splitter=QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(4)
        self.splitter.setChildrenCollapsible(False)
        self.chat=QWidget()
        self.chat.setObjectName('chat')
        self.chat.setMinimumWidth(350)
        cv=QVBoxLayout(self.chat)
        cv.setContentsMargins(0,0,0,0)
        cv.setSpacing(0)
        self.history_stack=QStackedWidget()
        empty=QWidget()
        el=QVBoxLayout(empty)
        el.setContentsMargins(24,25,24,40)
        el.addStretch()
        t=label('今天想转换什么文档？','emptyTitle')
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setWordWrap(True)
        el.addWidget(t)
        el.addSpacing(12)
        t=label('添加或拖入文件，生成可以阅读和复制的 Markdown。','muted')
        t.setWordWrap(True)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(t)
        el.addSpacing(24)
        t=label('PDF  ·  Word  ·  PPT  ·  Excel','small')
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(t)
        el.addStretch()
        self.history_stack.addWidget(empty)
        self.scroll=QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        viewport=QWidget()
        viewport.setObjectName('conversation')
        center=QHBoxLayout(viewport)
        center.setContentsMargins(22,24,22,22)
        center.setSpacing(0)
        center.addStretch(1)
        self.history=QWidget()
        self.history.setMaximumWidth(760)
        self.history.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Minimum)
        self.history_layout=QVBoxLayout(self.history)
        self.history_layout.setContentsMargins(0,0,0,0)
        self.history_layout.setSpacing(32)
        self.history_layout.addStretch(1)
        center.addWidget(self.history,20,Qt.AlignmentFlag.AlignTop)
        center.addStretch(1)
        self.scroll.setWidget(viewport)
        self.history_stack.addWidget(self.scroll)
        cv.addWidget(self.history_stack,1)
        composer_center=QHBoxLayout()
        composer_center.setContentsMargins(22,12,22,0)
        composer_center.setSpacing(0)
        composer_center.addStretch(1)
        self.composer=QFrame()
        self.composer.setObjectName('composer')
        self.composer.setMaximumWidth(760)
        self.composer.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        cp=QVBoxLayout(self.composer)
        cp.setContentsMargins(14,14,14,12)
        cp.setSpacing(12)
        self.composer_title=label('添加文件，开始转换','muted')
        self.composer_title.setStyleSheet('padding: 3px 7px;')
        self.composer_title.setWordWrap(True)
        cp.addWidget(self.composer_title)
        self.progress=QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        cp.addWidget(self.progress)
        cr=QHBoxLayout()
        cr.setContentsMargins(0,0,0,0)
        cr.setSpacing(4)
        self.add_btn=button('添加文件',self.choose_files,'add','subtle')
        cr.addWidget(self.add_btn)
        self.folder_btn=button('保存位置',self.choose_folder,'folder','subtle')
        self.folder_btn.setToolTip(str(self.folder))
        cr.addWidget(self.folder_btn)
        cr.addStretch()
        self.stop_btn=tool('stop','停止后续任务（等待当前文件完成）',self.stop_conversion,36)
        self.stop_btn.hide()
        cr.addWidget(self.stop_btn)
        self.start_btn=button('',self.start_conversion,'send','send')
        self.start_btn.setFixedSize(36,36)
        self.start_btn.setIconSize(QSize(20,20))
        self.start_btn.setAccessibleName('开始转换')
        self.start_btn.setToolTip('开始转换 · Ctrl+Enter')
        cr.addWidget(self.start_btn)
        cp.addLayout(cr)
        composer_center.addWidget(self.composer,20)
        composer_center.addStretch(1)
        cv.addLayout(composer_center)
        self.summary=label('','small')
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary.setWordWrap(True)
        self.summary.setContentsMargins(24,10,24,0)
        cv.addWidget(self.summary)
        limits=label('本地转换 · 扫描件需先 OCR，公式和复杂表格请核对','small')
        limits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        limits.setWordWrap(True)
        limits.setContentsMargins(22,9,22,17)
        limits.setStyleSheet('font-size: 11px; color: #a0a0a0;')
        cv.addWidget(limits)
        self.splitter.addWidget(self.chat)
        self.viewer=ViewerPanel()
        self.viewer.count_changed.connect(self.panel_count)
        self.viewer.expand_requested.connect(self.toggle_expand)
        self.viewer.notify.connect(self.notify)
        self.splitter.addWidget(self.viewer)
        self.viewer.hide()
        layout.addWidget(self.splitter,1)
        self.close_timer=QTimer(self)
        self.close_timer.timeout.connect(self.finish_close)

    def notify(self,text):
        self.summary.setText(text)
    def choose_files(self):
        if self.busy:
            return
        names,_=QFileDialog.getOpenFileNames(self,'添加要转换的文档','',
            '支持的文件 (*.pdf *.docx *.pptx *.xlsx *.xls *.html *.htm *.csv *.json *.txt *.md *.xml);;所有文件 (*)')
        if names:
            self.add_files(names)
    def add_files(self,names):
        if self.busy:
            self.notify('当前批次完成后，可以继续添加文件。')
            return
        seen={os.path.normcase(str(e.path.resolve())) for e in self.entries}
        added=duplicate=unsupported=0
        for raw in names:
            path=Path(raw).resolve()
            key=os.path.normcase(str(path))
            if key in seen:
                duplicate+=1
                continue
            if path.suffix.lower() not in SUPPORTED or not path.is_file():
                unsupported+=1
                continue
            entry=Entry(path)
            self.entries.append(entry)
            exchange=Exchange(entry,self)
            self.exchanges[entry.id]=exchange
            self.history_layout.insertWidget(self.history_layout.count()-1,exchange)
            seen.add(key)
            added+=1
        self.update_controls()
        self.scroll_bottom()
        bits=[f'已添加 {added} 个文件']
        if duplicate:
            bits.append(f'{duplicate} 个重复文件已跳过')
        if unsupported:
            bits.append(f'{unsupported} 个不支持的文件已跳过')
        self.notify('；'.join(bits))
    def scroll_bottom(self):
        QTimer.singleShot(20,self,lambda:self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
    def entry(self,entry_id):
        return next((e for e in self.entries if e.id==entry_id),None)
    def remove_entry(self,entry_id):
        if self.busy:
            return
        e=self.entry(entry_id)
        if not e:
            return
        widget=self.exchanges.pop(entry_id)
        self.history_layout.removeWidget(widget)
        widget.deleteLater()
        self.entries.remove(e)
        self.update_controls()
        self.notify('已移除这条文件记录，原文件和保存结果仍保留。')
    def clear_queue(self):
        if self.busy:
            return
        for widget in self.exchanges.values():
            self.history_layout.removeWidget(widget)
            widget.deleteLater()
        self.entries.clear()
        self.exchanges.clear()
        self.viewer.clear()
        self.close_viewer()
        self.update_controls()
        self.notify('已开始新的转换；原文件和已保存的结果仍保留。')
    def choose_folder(self):
        if self.busy:
            return
        chosen=QFileDialog.getExistingDirectory(self,'选择结果保存位置',str(self.folder))
        if chosen:
            self.set_folder(Path(chosen))
            self.notify('保存位置已更改。')
    def set_folder(self,folder):
        self.folder=Path(folder)
        self.folder_btn.setToolTip(str(self.folder))
        if not self.test_mode:
            self.settings.setValue('output',str(self.folder))
    def update_controls(self):
        waiting=sum(e.state=='waiting' for e in self.entries)
        failed=sum(e.state=='failed' for e in self.entries)
        self.start_btn.setEnabled(bool(waiting+failed) and not self.busy)
        self.add_btn.setEnabled(not self.busy)
        self.folder_btn.setEnabled(not self.busy)
        self.clear_btn.setEnabled(bool(self.entries) and not self.busy)
        self.stop_btn.setVisible(self.busy)
        self.progress.setVisible(self.busy)
        if self.busy:
            self.composer_title.setText('正在转换，完成文件会出现在对话左侧…')
        elif waiting:
            self.composer_title.setText(f'{waiting} 个文件已准备好，点击发送按钮开始转换')
        elif failed:
            self.composer_title.setText(f'{failed} 个文件失败，点击发送按钮重试')
        elif self.entries:
            self.composer_title.setText('继续添加文档，或点击文件查看内容')
        else:
            self.composer_title.setText('添加文件，开始转换')
        self.history_stack.setCurrentIndex(1 if self.entries else 0)
        for row in self.exchanges.values():
            row.refresh()
    def start_conversion(self,only=None):
        if self.busy:
            return
        pending=[e for e in self.entries if e.state in {'waiting','failed'} and (not isinstance(only,str) or e.id==only)]
        if not pending:
            return
        for e in pending:
            e.state='waiting'
            e.error=''
        self.busy=True
        self.stop_btn.setEnabled(True)
        self.progress.setRange(0,len(pending))
        self.progress.setValue(0)
        self.worker=ConversionWorker(pending,self.folder)
        self.worker.started_item.connect(self.item_started)
        self.worker.result.connect(self.item_result)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.conversion_finished)
        self.update_controls()
        self.notify(f'正在准备转换组件，共 {len(pending)} 个文件。')
        self.worker.start()
    def retry_entry(self,entry_id):
        self.start_conversion(entry_id)
    def item_started(self,entry_id):
        e=self.entry(entry_id)
        e.state='running'
        self.exchanges[entry_id].refresh()
        self.notify('正在转换：'+e.path.name)
    def item_result(self,entry_id,success,output,text,error):
        e=self.entry(entry_id)
        e.state='success' if success else 'failed'
        e.output=Path(output) if success else None
        e.text=text
        e.error=error
        self.exchanges[entry_id].refresh()
    def on_progress(self,done,total):
        self.progress.setValue(done)
        self.progress.setAccessibleName(f'已处理 {done} 个，共 {total} 个')
    def stop_conversion(self):
        if self.busy and self.worker:
            self.worker.stop_requested.set()
            self.stop_btn.setEnabled(False)
            self.notify('正在停止后续任务；当前文件处理完成后，剩余文件会保留。')
    def conversion_finished(self):
        self.busy=False
        worker=self.worker
        self.worker=None
        worker.deleteLater()
        good=sum(e.state=='success' for e in self.entries)
        bad=sum(e.state=='failed' for e in self.entries)
        waiting=sum(e.state=='waiting' for e in self.entries)
        self.update_controls()
        bits=[f'已完成 {good} 个文件']
        if bad:
            bits.append(f'{bad} 个失败，可查看原因并重试')
        if waiting:
            bits.append(f'{waiting} 个等待转换')
        self.notify('；'.join(bits))
        self.batch_finished.emit()
        if self.closing:
            self.finish_close()
    def open_entry(self,entry_id,result):
        e=self.entry(entry_id)
        if not e or (result and e.state!='success'):
            return None
        path=e.output if result else e.path
        if not path.is_file():
            self.notify('文件已移动或删除，请重新选择。')
            return None
        self.show_viewer()
        text=e.text if result or (e.state=='success' and e.path.suffix.lower() in {'.docx','.pptx','.xlsx','.xls'}) else None
        tab=self.viewer.open_file((entry_id,'result' if result else 'source'),path,text,extracted=not result and text is not None)
        for row in self.exchanges.values():
            for card in [row.source_card,row.result_card]:
                card.setProperty('selected',card.path==path)
                card.style().unpolish(card)
                card.style().polish(card)
        return tab
    def show_viewer(self):
        self.chat.show()
        self.expanded=False
        first=not self.viewer.isVisible()
        self.viewer.show()
        if first:
            self.splitter.setSizes([460,700])
        self.panel_btn.setToolTip('收起文件预览')
    def close_viewer(self):
        self.viewer.hide()
        self.chat.show()
        self.expanded=False
        self.panel_btn.setToolTip('打开文件预览')
    def toggle_viewer(self):
        if self.viewer.isVisible():
            self.close_viewer()
        else:
            self.show_viewer()
    def toggle_expand(self):
        self.expanded=not self.expanded
        self.chat.setVisible(not self.expanded)
    def panel_count(self,count):
        self.panel_btn.setText(str(count))
    def copy_entry(self,entry_id):
        e=self.entry(entry_id)
        if e and e.state=='success':
            QApplication.clipboard().setText(e.text)
            self.notify(f'已复制 {len(e.text):,} 个字符。')
    def open_entry_folder(self,entry_id):
        e=self.entry(entry_id)
        folder=e.output.parent if e and e.output else self.folder
        try:
            folder.mkdir(parents=True,exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except OSError:
            self.notify('无法打开这个保存位置，请选择其他文件夹。')
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and not self.busy:
            event.acceptProposedAction()
    def dropEvent(self,event):
        self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()
    def finish_close(self):
        if self.closing and not self.busy and not self.viewer.has_jobs():
            self.close_timer.stop()
            self.close()
    def closeEvent(self,event):
        if self.busy or self.viewer.has_jobs():
            self.closing=True
            self.stop_conversion()
            self.notify('当前文件读取完成后，程序将自动关闭。')
            self.close_timer.start(100)
            event.ignore()
        else:
            event.accept()

def main():
    if sys.stdout is None:
        sys.stdout=open(os.devnull,'w',encoding='utf-8')
    if sys.stderr is None:
        sys.stderr=open(os.devnull,'w',encoding='utf-8')
    app=QApplication(sys.argv)
    app.setApplicationName('MarkItDown')
    app.setApplicationVersion(VERSION)
    app.setStyle('Fusion')
    palette=QPalette()
    for role,color in [(QPalette.ColorRole.Window,'#181818'),(QPalette.ColorRole.WindowText,'#f1f1f1'),
        (QPalette.ColorRole.Base,'#181818'),(QPalette.ColorRole.Text,'#f1f1f1'),
        (QPalette.ColorRole.Button,'#292929'),(QPalette.ColorRole.ButtonText,'#f1f1f1'),
        (QPalette.ColorRole.Highlight,'#365b90')]:
        palette.setColor(role,QColor(color))
    app.setPalette(palette)
    app.setFont(QFont('Microsoft YaHei UI',10))
    app.setStyleSheet(STYLE)
    # CPython can otherwise collect Python/Qt cycles in a conversion worker.
    # QObject wrappers and widgets must be released on the GUI thread.
    gc.disable()
    app.gc_timer=QTimer(app)
    app.gc_timer.setInterval(2000)
    app.gc_timer.timeout.connect(gc.collect)
    app.gc_timer.start()
    app.aboutToQuit.connect(gc.collect)
    log_dir=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    log_dir.mkdir(parents=True,exist_ok=True)
    from logging.handlers import RotatingFileHandler
    handler=RotatingFileHandler(log_dir/'conversion.log',maxBytes=1000000,backupCount=2,encoding='utf-8')
    logging.basicConfig(handlers=[handler],level=logging.WARNING)
    if '--verify' in sys.argv:
        from verification import run_verification
        run_verification(app,Path(sys.argv[sys.argv.index('--verify')+1]))
    else:
        app.window=MainWindow()
        app.window.show()
        incoming=[p for p in sys.argv[1:] if Path(p).is_file()]
        if incoming:
            app.window.add_files(incoming)
    return app.exec()
if __name__=='__main__':
    sys.exit(main())
