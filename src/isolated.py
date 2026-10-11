"""Disposable conversion process; only the parent publishes completed results."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from conversion import UserError, save_atomic
from quality import report_path,publish_report


class Cancelled(Exception):
    pass


def run_job(jobfile):
    import socket
    def blocked(*args, **kwargs):
        raise OSError('Network connections are disabled in the local conversion worker')
    socket.socket.connect=blocked
    from conversion import make_converter, convert_one, friendly_error
    job=json.loads(Path(jobfile).read_text(encoding='utf-8'))
    root=Path(jobfile).parent
    def progress(message):
        temporary=root/'progress.tmp'
        temporary.write_text(message,encoding='utf-8')
        os.replace(temporary,root/'progress.txt')
    options=job.get('options') or {};options['_progress']=progress
    try:
        progress('正在加载本地转换组件')
        if options.get('direction')=='md-to-docx':
            from word_export import export_word
            target,_=export_word(Path(job['source']),root/'result',options)
        else:
            target,_=convert_one(make_converter(),Path(job['source']),root/'result',options)
        reply={'target':str(target)}
    except Exception as exc:
        reply={'error':friendly_error(exc)}
    (root/'reply.json').write_text(json.dumps(reply,ensure_ascii=False),encoding='utf-8')


def convert_isolated(source,folder,stop,progress=None,options=None):
    with tempfile.TemporaryDirectory(prefix='markitdown-job-') as raw:
        root=Path(raw)
        job=root/'job.json'
        job.write_text(json.dumps({'source':str(source),'options':options or {}},ensure_ascii=False),encoding='utf-8')
        command=[sys.executable]
        if not getattr(sys,'frozen',False):command.append(str(Path(__file__).with_name('launcher.py')))
        command+=['--convert-job',str(job)]
        if stop.is_set():raise Cancelled()
        if progress:progress('独立进程正在读取和转换')
        environment=os.environ.copy();environment['TEMP']=str(root);environment['TMP']=str(root)
        process=subprocess.Popen(command,env=environment,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        previous_progress=''
        try:
            while process.poll() is None:
                if stop.wait(.1):
                    if os.name=='nt':
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    else:process.kill()
                    process.wait()
                    raise Cancelled()
                if progress:
                    try:
                        current=(root/'progress.txt').read_text(encoding='utf-8')
                        if current!=previous_progress:progress(current);previous_progress=current
                    except OSError:pass
            if stop.is_set():raise Cancelled()
            if process.returncode or not (root/'reply.json').exists():
                raise UserError('独立转换进程异常退出，未发布半成品。可以重试。')
            reply=json.loads((root/'reply.json').read_text(encoding='utf-8'))
            if 'error' in reply:raise UserError(reply['error'])
            temporary=Path(reply['target'])
            if temporary.suffix.lower()=='.docx':
                from word_export import inspect_docx,publish_binary
                facts=inspect_docx(temporary)
                if stop.is_set():raise Cancelled()
                final=publish_binary(temporary,folder,Path(source).stem)
                try:publish_report(final,json.loads(report_path(temporary).read_text(encoding='utf-8')))
                except Exception:final.unlink(missing_ok=True);raise
                return final,facts['text']
            text=temporary.read_text(encoding='utf-8')
            if progress:progress('转换和诊断已完成，正在保存')
            if stop.is_set():raise Cancelled()
            folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
            moved=[];final=None
            try:
                for directory in temporary.parent.glob('assets-*'):
                    destination=folder/directory.name
                    if destination.exists():raise FileExistsError(destination)
                    os.rename(directory,destination);moved.append(destination)
                final=save_atomic(folder,Path(source).stem,text)
                publish_report(final,json.loads(report_path(temporary).read_text(encoding='utf-8')))
            except Exception:
                if final:final.unlink(missing_ok=True)
                for directory in moved:
                    assert directory.resolve().parent==folder and directory.name.startswith('assets-')
                    shutil.rmtree(directory)
                raise
            return final,text
        finally:
            if process.poll() is None:
                process.kill();process.wait()
