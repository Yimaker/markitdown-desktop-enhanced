"""Disk-backed UTF-8 chunks; preview memory is independent of document length."""
import bisect
import os
import tempfile
from pathlib import Path

CHUNK=60000

class PagedText:
    def __init__(self,path,owned=False):
        self.path=Path(path);self.owned=owned;self.offsets=[];self.starts=[];self.length=0
        with self.path.open('r',encoding='utf-8-sig',newline=None) as stream:
            while True:
                offset=stream.tell();text=stream.read(CHUNK)
                if not text:break
                self.offsets.append(offset);self.starts.append(self.length);self.length+=len(text)
        if not self.offsets:self.offsets=[0];self.starts=[0]
    @classmethod
    def from_text(cls,text):
        fd,name=tempfile.mkstemp(prefix='markitdown-preview-',suffix='.txt')
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as stream:stream.write(text)
        return cls(name,True)
    def get(self,index):
        with self.path.open('r',encoding='utf-8-sig',newline=None) as stream:
            stream.seek(self.offsets[index]);return stream.read(CHUNK)
    def locate(self,position):
        index=max(0,bisect.bisect_right(self.starts,position)-1)
        return index,position-self.starts[index]
    def find(self,query,start=0):
        carry=''
        for index in range(len(self.offsets)):
            chunk=self.get(index);combined=carry+chunk;base=self.starts[index]-len(carry)
            found=combined.find(query,max(0,start-base))
            if found>=0:return base+found
            carry=combined[-max(0,len(query)-1):] if len(query)>1 else ''
        return -1
    def full_text(self):
        return ''.join(self.get(i) for i in range(len(self.offsets)))
    def close(self):
        if self.owned:self.path.unlink(missing_ok=True);self.owned=False

def save_edited(source,text,folder,record_history=True):
    import json
    from assets import Assets
    from conversion import save_atomic
    from quality import read_report,report_path,publish_report
    source=Path(source);folder=Path(folder);report=read_report(source)
    assets=Assets(folder);target=None
    try:
        for item in report.get('assets',[]):
            original=(source.parent/item['path']).resolve()
            if original.is_relative_to(source.parent.resolve()) and original.is_file() and original.parent.name.startswith('assets-'):
                copied=assets.add(original.read_bytes(),original.suffix,item.get('label','原结果资产'))
                text=text.replace(item['path'],copied)
            else:
                from conversion import UserError
                raise UserError('引用的原结果资产缺失或路径不安全，未保存不完整副本。请恢复资产目录后重试。')
        if not assets.files:assets.cleanup()
        target=save_atomic(folder,source.stem+'-编辑版',text)
        report.update(status='review',label='编辑副本 · 需要核对',edited_from=str(source.resolve()),assets=assets.files,output_characters=len(text))
        report['issues']=['此副本经过人工编辑，原有自动诊断不能证明编辑后内容正确。']+report.get('issues',[])
        publish_report(target,report)
    except Exception:
        if target:target.unlink(missing_ok=True)
        assets.cleanup();raise
    if record_history:
        from history_store import HistoryStore
        # An indexing failure must not delete a successfully saved edit.
        try:HistoryStore().record(report.get('source',source),target,text,report['label'])
        except Exception:pass
    return target

