"""Fetch only the pinned official Pandoc build, checking archive and binary digests."""
from pathlib import Path, PurePosixPath
import hashlib, json, shutil, tempfile, urllib.request, zipfile

VERSION='3.12.1'
URL='https://github.com/jgm/pandoc/releases/download/3.12.1/pandoc-3.12.1-windows-x86_64.zip'
ARCHIVE_SHA256='6ef431cb20b2c24a0371fc19200dc49d452be54b1b5c9239f3462841ef53e587'
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    root=Path(__file__).resolve().parents[1]
    destination=root/'src/resources/pandoc'
    expected=json.loads((destination/'provenance.json').read_text(encoding='utf-8'))['binary_sha256']
    binary=destination/'pandoc.exe'
    if binary.is_file() and sha(binary)==expected:
        print('Verified Pandoc '+VERSION+' is already present.');return
    destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='markitdown-pandoc-') as raw:
        archive=Path(raw)/'pandoc.zip'
        with urllib.request.urlopen(URL,timeout=180) as response,archive.open('wb') as output:
            shutil.copyfileobj(response,output)
        if sha(archive)!=ARCHIVE_SHA256:raise RuntimeError('Official Pandoc archive checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            for filename in ['pandoc.exe','COPYING.rtf','COPYRIGHT.txt','MANUAL.html']:
                name=next(n for n in z.namelist() if n.endswith('/'+filename))
                assert '..' not in PurePosixPath(name).parts
                with z.open(name) as source,(destination/filename).open('wb') as output:
                    shutil.copyfileobj(source,output)
        if sha(binary)!=expected:raise RuntimeError('Pandoc executable checksum mismatch')
    print('Verified official Pandoc '+VERSION+' prepared.')
if __name__=='__main__':main()
