"""Native Qt integration checks for the shipped conversation UI and local viewer."""
from __future__ import annotations
import hashlib
import json
import shutil
import socket
import sys
import time
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QMimeData,QUrl,QPointF,QPoint,QObject,Slot,QSize
from PySide6.QtGui import QDragEnterEvent,QDropEvent,QDesktopServices,QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QTabBar
from app import MainWindow, VERSION

class UrlCapture(QObject):
    def __init__(self):
        super().__init__()
        self.urls=[]
    @Slot(QUrl)
    def handle(self,url):
        self.urls.append(url.toLocalFile())

class Verifier(QObject):
    def __init__(self,app,root):
        super().__init__()
        self.app=app
        self.root=root.resolve()
        self.config=json.loads((self.root/'fixtures.json').read_text(encoding='utf-8'))
        self.window=MainWindow(True)
        self.window.show()
        self.stage=''
        self.checks=[]
        self.heartbeat=0
        self.start_time=time.monotonic()
        self.report={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),
            'executable':sys.executable,'bundle_root':getattr(sys,'_MEIPASS',None),
            'method':'Native Qt window.grab, QTest input, real QThread converters and Qt PDF rendering. Not manual mouse testing. External-open paths intercepted during tests.',
            'checks':self.checks}
        self.network_attempts=[]
        self.original_connect=socket.socket.connect
        def deny_connect(sock,address):
            self.network_attempts.append(str(address))
            raise OSError('Python network connections disabled for verification')
        socket.socket.connect=deny_connect
        self.urls=UrlCapture()
        QDesktopServices.setUrlHandler('file',self.urls,'handle')
        self.timer=QTimer(self)
        self.timer.timeout.connect(lambda:setattr(self,'heartbeat',self.heartbeat+1))
        self.timer.start(50)
        self.timeout=QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda:self.fail('Verification timed out'))
        self.timeout.start(240000)
        self.window.batch_finished.connect(lambda:QTimer.singleShot(180,self.advance))
        self.hashes={f['path']:self.sha(Path(f['path'])) for f in self.config['official']}
        QTimer.singleShot(250,self.begin)
    def sha(self,p):
        return hashlib.sha256(p.read_bytes()).hexdigest()
    def check(self,name,ok,detail=''):
        self.checks.append({'name':name,'passed':bool(ok),'detail':detail})
        (self.root/'progress.json').write_text(json.dumps({'stage':self.stage,'last_check':self.checks[-1],'count':len(self.checks)},ensure_ascii=False,indent=2),encoding='utf-8')
        if not ok:
            raise AssertionError(name+': '+str(detail))
    def grab(self,name):
        # Qt's PDF page renderer and layout updates are asynchronous.
        QTest.qWait(350)
        QApplication.processEvents()
        self.window.grab().save(str(self.root/name))
    def begin(self):
        try:
            w=self.window
            self.grab('01-empty.png')
            self.check('viewer initially collapsed',not w.viewer.isVisible())
            self.check('empty conversion action disabled',not w.start_btn.isEnabled())
            w.set_folder(self.root/'中文 输出 results')
            names=[f['path'] for f in self.config['official']]
            mime=QMimeData()
            mime.setUrls([QUrl.fromLocalFile(p) for p in names])
            drag=QDragEnterEvent(w.rect().center(),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(w,drag)
            drop=QDropEvent(QPointF(w.rect().center()),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(w,drop)
            self.check('native file drop accepted',drop.isAccepted() and len(w.entries)==5)
            w.add_files(names)
            self.check('duplicate input skipped',len(w.entries)==5)
            self.bad=self.root/'损坏 文件.docx'
            self.bad.write_bytes(b'not a valid office file')
            w.add_files([str(self.bad)])
            self.grab('02-queued.png')
            QTest.mouseClick(w.exchanges[w.entries[1].id].source_card,Qt.MouseButton.LeftButton)
            office=w.viewer.tabs.currentWidget()
            self.office=office
            if office.ready:
                QTimer.singleShot(50,self.start_official)
            else:
                office.worker.loaded.connect(lambda *_:QTimer.singleShot(50,self.start_official))
        except Exception as exc:
            self.fail(str(exc))
    def start_official(self):
        try:
            w=self.window
            office=self.office
            self.check('Office source preview before conversion uses background extraction',office.ready and self.config['official'][1]['must_include'][0] in office.text,office.message_body.text())
            self.check('Office preview labelled extracted text','提取文本' in office.note.full)
            w.viewer.clear()
            w.close_viewer()
            self.stage='official'
            self.before_batch=self.heartbeat
            QTest.mouseClick(w.start_btn,Qt.MouseButton.LeftButton)
        except Exception as exc:
            self.fail(str(exc))
    def advance(self):
        try:
            w=self.window
            if self.stage=='append':
                self.check('packaged appended task remains available after active batch',w.entries[0].state=='success' and w.entries[1].state=='waiting')
                self.report.update(passed=True,elapsed_seconds=round(time.monotonic()-self.start_time,2),heartbeat_ticks=self.heartbeat,bundle_inventory=self.inventory())
                self.finish(0)
            elif self.stage=='official':
                for vector,e in zip(self.config['official'],w.entries[:5]):
                    self.check('official conversion '+e.path.suffix,e.state=='success',e.error)
                    missing=[s for s in vector['must_include'] if s not in e.text]
                    from quality import read_report
                    import re
                    assets=read_report(e.output).get('assets',[])
                    for expected in missing[:]:
                        match=re.fullmatch(r'!\[(.*?)\]\([^)]+\)',expected)
                        if match and any(f'![{match[1]}]({a["path"]})' in e.text and (e.output.parent/a['path']).is_file() and self.sha(e.output.parent/a['path'])==a['sha256'] for a in assets):
                            missing.remove(expected)
                    # The upstream placeholder is intentionally replaced by a usable
                    # relative PNG reference; require actual exported bytes instead.
                    if 'data:image/png;base64...' in missing:
                        from quality import read_report
                        assets=read_report(e.output).get('assets',[])
                        if any(a['path'].endswith('.png') and a['path'] in e.text and (e.output.parent/a['path']).is_file() and self.sha(e.output.parent/a['path'])==a['sha256'] for a in assets):
                            missing.remove('data:image/png;base64...')
                    extra=[s for s in vector['must_not_include'] if s in e.text]
                    self.check('official content '+e.path.suffix,not missing and not extra,{'missing':missing,'forbidden':extra,'characters':len(e.text)})
                    self.check('UTF-8 saved '+e.path.suffix,e.output.read_text(encoding='utf-8')==e.text)
                self.check('corrupt input isolated',w.entries[-1].state=='failed' and w.entries[-1].output is None)
                self.check('corrupt input has no final file',not (w.folder/(self.bad.stem+'.md')).exists())
                self.check('original hashes unchanged',all(self.sha(Path(p))==h for p,h in self.hashes.items()))
                self.check('no temporary output remains',not list(w.folder.glob('*.tmp')))
                self.check('background UI heartbeat',self.heartbeat-self.before_batch>=3,self.heartbeat-self.before_batch)
                first=w.entries[0]
                row=w.exchanges[first.id]
                w.scroll.ensureWidgetVisible(row)
                QApplication.processEvents()
                src=row.source_card.mapTo(w.history,QPoint(0,0))
                res=row.result_card.mapTo(w.history,QPoint(0,0))
                self.check('source right and result left',src.x()+row.source_card.width()/2>w.history.width()/2 and res.x()+row.result_card.width()/2<w.history.width()/2,{'source_x':src.x(),'result_x':res.x(),'width':w.history.width()})
                self.grab('03-conversation.png')
                QTest.mouseClick(row.source_card,Qt.MouseButton.LeftButton)
                pdf=w.viewer.tabs.currentWidget()
                self.check('source click opens native PDF',w.viewer.isVisible() and pdf.pdf_document and pdf.ready)
                self.check('native PDF pages and rendered image',pdf.pdf_document.pageCount()>0 and not pdf.pdf_document.render(0,QSize(300,400)).isNull())
                pdf.zoom.setCurrentIndex(3)
                self.check('PDF zoom changes',abs(pdf.pdf_view.zoomFactor()-1)<.001)
                pdf.zoom.setCurrentIndex(0)
                self.grab('04-pdf-preview.png')
                QTest.mouseClick(row.result_card,Qt.MouseButton.LeftButton)
                md=w.viewer.tabs.currentWidget()
                self.check('result click opens Markdown tab',md.path==first.output and md.text==first.text and w.viewer.tabs.count()==2)
                self.check('panel count matches opened tabs',w.panel_btn.text()=='2')
                self.grab('05-markdown-preview.png')
                if md.raw_btn.isChecked():
                    QTest.mouseClick(md.raw_btn,Qt.MouseButton.LeftButton)
                QTest.mouseClick(md.raw_btn,Qt.MouseButton.LeftButton)
                self.check('Markdown raw view toggle',md.stack.currentWidget() is md.raw)
                QTest.mouseClick(md.copy_btn,Qt.MouseButton.LeftButton)
                self.check('preview copies full result',QApplication.clipboard().text()==first.text)
                QTest.mouseClick(md.raw_btn,Qt.MouseButton.LeftButton)
                self.check('Markdown reading view toggle',md.stack.currentWidget() is md.reader)
                QTest.mouseClick(row.copy_btn,Qt.MouseButton.LeftButton)
                self.check('conversation copies full result',QApplication.clipboard().text()==first.text)
                QTest.mouseClick(row.folder_btn,Qt.MouseButton.LeftButton)
                md.open_external()
                self.check('local open actions use real saved paths',[Path(x) for x in self.urls.urls[-2:]]==[w.folder,first.output])
                resource=md.reader.loadResource(QTextDocument.ResourceType.ImageResource,QUrl('https://example.invalid/test.png'))
                self.check('Markdown external resources blocked',resource.isEmpty())
                QTest.mouseClick(w.panel_btn,Qt.MouseButton.LeftButton)
                self.check('panel closes without dropping tabs',not w.viewer.isVisible() and w.viewer.tabs.count()==2)
                QTest.mouseClick(w.panel_btn,Qt.MouseButton.LeftButton)
                self.check('panel reopens preserving selected file',w.viewer.isVisible() and w.viewer.tabs.currentWidget() is md)
                w.open_entry(first.id,True)
                self.check('repeated file click reuses existing tab',w.viewer.tabs.count()==2)
                for e in w.entries[1:5]:
                    tab=w.open_entry(e.id,False)
                    self.check('Office source preview after conversion '+e.path.suffix,tab.ready and tab.text==e.text and '提取文本' in tab.note.full)
                    w.viewer.close_widget(tab)
                close=w.viewer.tabs.tabBar().tabButton(1,QTabBar.ButtonPosition.RightSide)
                QTest.mouseClick(close,Qt.MouseButton.LeftButton)
                self.check('tab close updates count',w.viewer.tabs.count()==1 and w.panel_btn.text()=='1')
                w.close_viewer()
                w.scroll.ensureWidgetVisible(w.exchanges[w.entries[-1].id])
                self.grab('07-error.png')
                self.check('file error and retry control visible','损坏' in w.exchanges[w.entries[-1].id].error_label.text() and w.exchanges[w.entries[-1].id].retry_btn.isVisible())
                shutil.copyfile(self.config['official'][1]['path'],self.bad)
                self.stage='retry'
                QTest.mouseClick(w.exchanges[w.entries[-1].id].retry_btn,Qt.MouseButton.LeftButton)
            elif self.stage=='retry':
                self.check('repaired failed file can retry',w.entries[-1].state=='success')
                old={p.name:self.sha(p) for p in w.folder.glob('*.md')}
                w.clear_queue()
                self.check('new conversion keeps old outputs',all(self.sha(w.folder/n)==h for n,h in old.items()) and w.viewer.tabs.count()==0)
                self.text=self.root/'中文 路径'/'课程 笔记.txt'
                self.text.parent.mkdir(exist_ok=True)
                self.text.write_text('中文转换测试：课程笔记。\n保留 English 与标点。',encoding='utf-8')
                other=self.root/'另一个 目录'/self.text.name
                other.parent.mkdir(exist_ok=True)
                other.write_text('第二个同名文件。',encoding='utf-8')
                html=self.root/'网页 示例.html'
                html.write_text('<h1>中文标题</h1><p>本地网页内容</p><script>bad-script</script>',encoding='utf-8')
                csv=self.root/'表格 示例.csv'
                csv.write_text('名称,数值\n中文,42\n',encoding='utf-8')
                js=self.root/'数据 示例.json'
                js.write_text('{"中文": "测试", "number": 7}',encoding='utf-8')
                w.add_files([str(self.text),str(other),str(html),str(csv),str(js)])
                self.stage='additional'
                w.start_conversion()
            elif self.stage=='additional':
                self.check('TXT HTML CSV JSON convert',all(e.state=='success' for e in w.entries),[(e.path.name,e.error) for e in w.entries])
                self.check('Chinese and spaces preserved','中文转换测试' in w.entries[0].text)
                self.check('same filename numbered',w.entries[0].output.name=='课程 笔记.md' and w.entries[1].output.name=='课程 笔记 (2).md')
                self.check('HTML scripts removed','中文标题' in w.entries[2].text and 'bad-script' not in w.entries[2].text)
                self.saved_hash=self.sha(w.entries[0].output)
                w.clear_queue()
                w.add_files([str(self.text)])
                self.stage='collision'
                w.start_conversion()
            elif self.stage=='collision':
                self.check('old output not overwritten',w.entries[0].output.name=='课程 笔记 (3).md' and self.sha(w.folder/'课程 笔记.md')==self.saved_hash)
                w.clear_queue()
                w.add_files([self.config['official'][0]['path'],str(self.text),self.config['official'][2]['path']])
                self.stage='cancel'
                w.start_conversion()
                w.worker.started_item.connect(lambda _:w.stop_conversion())
            elif self.stage=='cancel':
                self.check('stop terminates current process and leaves all tasks waiting',all(e.state=='waiting' for e in w.entries),[e.state for e in w.entries])
                w.clear_queue()
                w.add_files([str(self.text)])
                bad_folder=self.root/'这里是文件'
                bad_folder.write_text('occupied',encoding='utf-8')
                w.set_folder(bad_folder)
                self.stage='save-error'
                w.start_conversion()
            elif self.stage=='save-error':
                self.check('saving failure reported honestly',w.entries[0].state=='failed' and w.entries[0].output is None)
                w.clear_queue()
                w.set_folder(self.root/'中文 输出 results')
                longfile=self.text.parent/('用于检验中文长文件名显示和缩放的课程资料 '*4+'.txt')
                longfile.write_text(self.text.read_text(encoding='utf-8'),encoding='utf-8')
                self.longfile=longfile
                w.add_files([str(self.text),str(longfile)])
                QTest.mouseClick(w.exchanges[w.entries[0].id].remove_btn,Qt.MouseButton.LeftButton)
                self.check('remove one file record',len(w.entries)==1 and w.entries[0].path==longfile)
                self.stage='layout'
                w.start_conversion()
            elif self.stage=='layout':
                e=w.entries[0]
                w.open_entry(e.id,True)
                w.resize(900,650)
                self.grab('06-minimum-window.png')
                self.check('minimum size has visible composer and viewer',w.width()<=900 and w.chat.isVisible() and w.viewer.isVisible() and w.start_btn.isVisible())
                card=w.exchanges[e.id].source_card
                self.check('long source filename elides','…' in card.name.text() and str(e.path)==card.toolTip())
                w.resize(1180,800)
                w.clear_queue()
                reference=self.config.get('reference_pdf',self.config['official'][0]['path'])
                w.add_files([reference])
                self.stage='reference'
                w.start_conversion()
            elif self.stage=='reference':
                e=w.entries[0]
                self.check('reference document actually converted',e.state=='success',e.error)
                row=w.exchanges[e.id]
                self.grab('08-chat-reference.png')
                QTest.mouseClick(row.source_card,Qt.MouseButton.LeftButton)
                pdf=w.viewer.tabs.currentWidget()
                self.check('reference PDF native preview ready',pdf.ready and pdf.pdf_document.pageCount()>0)
                firstpage=pdf.pdf_document.getAllText(0).text()
                if self.config.get('reference_pdf'):
                    self.check('synthetic math PDF preview','SYNTHETIC_MATH_EXAMPLE' in firstpage and pdf.pdf_document.pageCount()>0)
                    self.check('mathematical PDF exponent and subscripts preserved',r'u_{n}-l_{n}=2^{-n}' in e.text and r'x^{2}' in e.text and r'a_{m}-a_{n}' in e.text)
                    self.check('compound math scripts and fractions preserved',r'2^{-(n+1)}' in e.text and r'l_{n+1}' in e.text and r'\frac{u_{n}-l_{n}}{2}' in e.text)
                    self.check('two synthetic drawn tables; no invented cross-page merge',len(__import__('re').findall(r'^\| ---',e.text,__import__('re').M))==2)
                    self.check('six Markdown problem headings',len(__import__('re').findall(r'^## 问题',e.text,__import__('re').M))==6)
                    extracted=e.text.split('## 原文资产与核对图')[0]
                    self.check('PDF repeated header/footer removed from extracted text; evidence image captions retain page numbers','SYNTHETIC_PAGE_HEADER' not in extracted and not __import__('re').search(r'第\s*\d+\s*页',extracted))
                pdf.jump_page(1)
                self.check('PDF page navigation',pdf.pdf_view.pageNavigator().currentPage()==min(1,pdf.pdf_document.pageCount()-1))
                pdf.jump_page(-1)
                self.grab('09-source-pdf.png')
                w.toggle_expand()
                self.check('viewer expands and hides conversation',w.expanded and not w.chat.isVisible())
                self.grab('10-expanded-preview.png')
                w.toggle_expand()
                self.check('return from expanded view',not w.expanded and w.chat.isVisible())
                QTest.mouseClick(row.result_card,Qt.MouseButton.LeftButton)
                self.grab('11-result-markdown.png')
                current=w.viewer.tabs.currentWidget()
                self.check('viewer header matches selected filename',current.title.full==e.output.name and (current.title.width()<current.title.fontMetrics().horizontalAdvance(current.title.full) or current.title.text()==current.title.full),{'full':current.title.full,'displayed':current.title.text(),'width':current.title.width()})
                self.check('source and result in independent tabs',w.viewer.tabs.count()==2 and w.viewer.tabs.currentWidget().path==e.output)
                self.check('no Python network connections needed',not self.network_attempts,self.network_attempts)
                sample=r'$x^{2}$ $\frac{a}{b}$ $$\frac{1}{1+\frac{a}{b}}$$ $$\begin{pmatrix}a&b\\c&d\end{pmatrix}$$'
                self.math_tab=w.viewer.open_file('math-check',self.root/'formula-check.md',sample)
                self.math_tab.show_math()
                self.math_tab.math_worker.finished.connect(lambda:QTimer.singleShot(100,self.finish_math))
        except Exception as exc:
            self.fail(str(exc))
    def finish_math(self):
        try:
            self.check('packaged local math renders exponent fraction nested fraction and matrix',len(self.math_tab.reader.math_images)==4)
            from math_preview import render_formula
            glyph=render_formula('x^{2}')
            self.check('packaged math exponent glyph pixels visible',sum(glyph.pixelColor(x,y).alpha()>0 for x in range(glyph.width()) for y in range(glyph.height()))>30)
            self.grab('12-local-math.png')
            self.window.compare_entry(self.window.entries[0].id)
            QTimer.singleShot(200,self.finish_comparison)
        except Exception as exc:self.fail(str(exc))
    def finish_comparison(self):
        try:
            tab=self.window.viewer.tabs.currentWidget()
            self.check('packaged side-by-side PDF and Markdown',tab.comparison is not None)
            tab.jump_page(1)
            self.check('packaged comparison page locator',tab.comparison.raw.textCursor().position()>0)
            # QPdfView renders asynchronously after navigation; wait for page ink,
            # not merely a changed page number or a blank white page rectangle.
            visible_ink=0
            for _ in range(30):
                QTest.qWait(100)
                page_image=tab.pdf_view.viewport().grab().toImage()
                visible_ink=sum(page_image.pixelColor(x,y).lightness()<180
                    for x in range(page_image.width()//5,page_image.width()*4//5,3)
                    for y in range(page_image.height()//5,page_image.height()*4//5,3))
                if visible_ink>30:break
            self.check('packaged comparison original page visibly rendered',visible_ink>30)
            self.grab('13-comparison.png')
            from history_store import HistoryStore
            self.long_path=self.root/'long-history-result.md'
            self.long_text='START\n'+'中文内容\n'*50000+'TAIL_FULL_TEXT_SEARCH'
            self.long_path.write_text(self.long_text,encoding='utf-8',newline='\n')
            self.long_hash=self.sha(self.long_path)
            store=HistoryStore(self.root/'history-test.sqlite3')
            store.record('independent source',self.long_path,self.long_text,'saved')
            self.check('packaged persistent history searches complete content',len(HistoryStore(self.root/'history-test.sqlite3').search('TAIL_FULL_TEXT_SEARCH'))==1)
            self.long_tab=self.window.viewer.open_file('long-check',self.long_path)
            self.long_tab.ready_changed.connect(lambda:QTimer.singleShot(100,self.finish_long_view))
        except Exception as exc:self.fail(str(exc))
    def finish_long_view(self):
        try:
            tab=self.long_tab
            self.check('packaged preview is disk-backed and chunked',tab.paged is not None and tab._text=='' and len(tab.raw.toPlainText())<=60000)
            tab.find_box.setText('TAIL_FULL_TEXT_SEARCH');tab.find_next()
            self.check('packaged search reaches beyond old preview cutoff',tab.raw.textCursor().selectedText()=='TAIL_FULL_TEXT_SEARCH')
            tab.edit_btn.setChecked(True);tab.toggle_edit();tab.raw.insertPlainText('EDITED_FINAL_TEXT')
            saved=tab.save_copy(self.root/'edited-copies',record_history=False)
            self.check('packaged editing saves complete new copy without changing original',saved.read_text(encoding='utf-8').endswith('EDITED_FINAL_TEXT') and self.sha(self.long_path)==self.long_hash)
            from PySide6.QtWidgets import QFileDialog
            folder=self.root/'folder-import';(folder/'nested').mkdir(parents=True,exist_ok=True)
            (folder/'nested'/'batch.txt').write_text('BATCH',encoding='utf-8')
            original=QFileDialog.getExistingDirectory
            QFileDialog.getExistingDirectory=lambda *args:str(folder)
            try:self.window.import_folder()
            finally:QFileDialog.getExistingDirectory=original
            self.check('packaged recursive folder import',any(e.path.name=='batch.txt' for e in self.window.entries))
            self.grab('14-long-editor.png')
            self.window.exchanges[self.window.entries[0].id].show_diagnostics()
            self.check('packaged diagnostics open in searchable scrollable viewer','诊断不等于正确率' in self.window.viewer.tabs.currentWidget().text)
            self.window.clear_queue()
            first=self.root/'append-first.txt';first.write_text('FIRST BATCH',encoding='utf-8')
            second=self.root/'append-second.txt';second.write_text('ADDED WHILE BUSY',encoding='utf-8')
            self.window.add_files([str(first)])
            self.stage='append';self.window.start_conversion()
            self.window.add_files([str(second)])
            self.check('packaged accepts files while converting',self.window.busy and len(self.window.entries)==2)
        except Exception as exc:self.fail(str(exc))
    def inventory(self):
        import magika
        base=Path(getattr(sys,'_MEIPASS',Path(magika.__file__).parent.parent))
        return {n:[str(p.relative_to(base)) for p in (base/n).rglob('*') if p.is_file() and p.suffix.lower() in {'.onnx','.json','.dll','.pyd'}] for n in ['magika','onnxruntime','PySide6']}
    def fail(self,error):
        self.report.update(passed=False,error=error)
        try:self.grab('failure.png')
        except Exception:pass
        self.finish(1)
    def finish(self,code):
        (self.root/'report.json').write_text(json.dumps(self.report,ensure_ascii=False,indent=2),encoding='utf-8')
        self.timeout.stop()
        socket.socket.connect=self.original_connect
        if self.window.busy:
            self.window.stop_conversion()
            self.window.batch_finished.connect(lambda:self.app.exit(code))
        else:
            QDesktopServices.unsetUrlHandler('file')
            self.window.close()
            self.app.exit(code)

def run_verification(app,root):
    app.verifier=Verifier(app,root)
