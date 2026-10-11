import os
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

class HistoryStore:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ.get('LOCALAPPDATA',Path.home()))/'MarkItDown'/'history.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS results (id INTEGER PRIMARY KEY, source TEXT, target TEXT UNIQUE, created TEXT, status TEXT, content TEXT)')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            yield db
            db.commit()
        finally:db.close()
    def record(self,source,target,text,status):
        with self.connect() as db:
            db.execute('INSERT INTO results(source,target,created,status,content) VALUES(?,?,?,?,?) ON CONFLICT(target) DO UPDATE SET content=excluded.content,status=excluded.status',
                       (str(source),str(Path(target).resolve()) if target else None,datetime.now().astimezone().isoformat(timespec='seconds'),status,text))
    def search(self,query=''):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,source,target,created,status FROM results WHERE ?="" OR instr(lower(source),lower(?))>0 OR instr(lower(content),lower(?))>0 OR instr(lower(status),lower(?))>0 ORDER BY id DESC',(query,query,query,query))]

def show_history(window,store=None):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QListWidget,QListWidgetItem,QLabel
    store=store or HistoryStore()
    dialog=QDialog(window);dialog.setWindowTitle('本地转换历史');dialog.resize(800,560)
    layout=QVBoxLayout(dialog)
    search=QLineEdit();search.setPlaceholderText('搜索文件名、转换结果全文或失败原因')
    layout.addWidget(search)
    results=QListWidget();layout.addWidget(results)
    note=QLabel('历史只保存在本机。双击重新打开结果；原文件和已保存结果不会被修改。');note.setWordWrap(True);layout.addWidget(note)
    def refresh():
        results.clear()
        for row in store.search(search.text()):
            name=Path(row['target'] or row['source']).name
            item=QListWidgetItem(f'{name}\n{row["created"]} · {row["status"]}')
            item.setData(Qt.ItemDataRole.UserRole,row);item.setToolTip(row['target'] or row['source']);results.addItem(item)
        note.setText(f'{results.count()} 条记录 · 搜索范围包含已存入历史的完整转换文字。外部修改结果后，索引不会自动更新。')
    def open_result(item):
        row=item.data(Qt.ItemDataRole.UserRole)
        if not row['target']:
            note.setText('这是一条失败记录：'+row['status']);return
        path=Path(row['target'])
        if not path.exists():note.setText('结果文件已移动或删除；历史记录仍保留原路径。');return
        if path.suffix.lower()=='.docx':
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)));dialog.hide();return
        window.viewer.open_file('history-'+str(path),path)
        window.show_viewer();dialog.hide()
    search.returnPressed.connect(refresh)
    actions=QHBoxLayout();find=QPushButton('全文搜索');find.clicked.connect(refresh);actions.addWidget(find)
    reopen=QPushButton('打开选中结果');reopen.clicked.connect(lambda:open_result(results.currentItem()) if results.currentItem() else None);actions.addWidget(reopen);layout.addLayout(actions)
    results.itemDoubleClicked.connect(open_result)
    refresh();dialog.show()
    window.history_dialog=dialog
