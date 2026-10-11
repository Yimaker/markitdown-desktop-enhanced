"""Explicit verification entry point; never runs during normal application use."""
import json,sys,traceback
from pathlib import Path
from PySide6.QtCore import QTimer
from app import MainWindow,VERSION

def run(app,root):
    if not getattr(sys,'frozen',False):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    w=MainWindow(test_mode=True);app.window=w;w.show();w.mode_combo.setCurrentIndex(1)
    report={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False))}
    def save(code):
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        w.close();app.exit(code)
    def finished():
        try:
            from quality import read_report
            from word_export import inspect_docx,parse,walk
            report['samples']=[]
            for e in w.entries:
                assert e.state=='success',e.error
                facts=inspect_docx(e.output);ast,_,_,_=parse(e.path)
                tables=[n for n in walk(ast) if n['t']=='Table']
                # Independently compare every source table cell's plain text and body row order.
                source_headers=[n['c'][2] for n in walk(ast) if n['t']=='Header']
                from word_export import inline_text
                positions=[facts['text'].find(inline_text(h)) for h in source_headers]
                assert all(x>=0 for x in positions) and positions==sorted(positions)
                expected=(1,1,2)  # Generated boundary fixture only; no personal reports.
                assert (facts['tables'],facts['images'],facts['omml'])==expected,facts
                assert not read_report(e.output)['issues'],read_report(e.output)['issues']
                report['samples'].append({'input':str(e.path),'output':str(e.output),'structure':{k:v for k,v in facts.items() if k!='text'},'heading_order':True})
            report['passed']=True;w.grab().save(str(root/'ui-completed.png'));save(0)
        except Exception:report['error']=traceback.format_exc();save(1)
    def begin():
        try:
            from test_word_export import run as checks
            report['boundaries']=checks(root/'boundaries')
            assert not w.appendix_check.isChecked()
            w.grab().save(str(root/'ui-word-mode.png'))
            source=root/'boundaries'/'中文 空格 (路径)'
            w.set_folder(root/'samples')
            w.add_files([str(source/'学习 笔记 (1).md')])
            w.batch_finished.connect(finished);w.start_conversion()
        except Exception:report['error']=traceback.format_exc();save(1)
    QTimer.singleShot(500,begin)
