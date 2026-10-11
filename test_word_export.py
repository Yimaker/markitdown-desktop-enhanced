"""Focused independent boundary assertions. Runs in source and frozen verification."""
from pathlib import Path
import hashlib,json,sys
from PIL import Image
from lxml import etree as ET
import zipfile
sys.path.insert(0,str(Path(__file__).parent/'src'))
from word_export import export_word,inspect_docx,NS,parse,walk
from quality import read_report
from conversion import UserError

def run(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);checks={}
    def check(name,yes):
        checks[name]=bool(yes)
        if not yes:raise AssertionError(name)
    inputs=root/'中文 空格 (路径)';inputs.mkdir(exist_ok=True)
    Image.new('RGB',(1600,400),'steelblue').save(inputs/'图 像 (1).png')
    source=inputs/'学习 笔记 (1).md'
    original=r'''# 原始标题

正文 **粗体** *斜体* file_name a_b_c $20 and $30，转义 \$x\$。

`a_b $x$ \frac{1}{2}`

```python
# 中文注释，代码符号原样保留
v = "a_b $x$ \\alpha"
```

1. 第一项
2. 第二项

- 条目甲
- 条目乙

| 姓名 | 数据 |
| --- | --- |
| 甲 | 12 |

![本地图片](<图 像 (1).png>)

[链接](https://example.com)

行内 $x_i^2 + \frac{a}{b} + \sqrt{x} + \alpha$。

$$
\forall x\in\mathbb{R},\exists y\in A\cup B: |x'|\le y < z \iff A\subseteq B \Rightarrow x\to y
$$

## 原文资产与核对图

### 核对一
![核对](<图 像 (1).png>)

## 后续章节

此章节必须保留。
'''
    source.write_text(original,encoding='utf-8');before=hashlib.sha256(source.read_bytes()).hexdigest()
    output,text=export_word(source,root/'out')
    report=read_report(output);facts=inspect_docx(output)
    check('Chinese spaces parentheses relative image',facts['images']==1)
    check('native formula constructs',facts['omml']==2 and not report['issues'])
    check('editable table rows columns',facts['table_shapes']==[[2,2]])
    check('literal underscore currency and code',all(x in text for x in ['file_name','a_b_c','$20','$30','a_b $x$','中文注释']))
    check('appendix default off later heading kept','此章节必须保留' in text and '核对一' not in text)
    check('input unchanged',before==hashlib.sha256(source.read_bytes()).hexdigest())
    hashout=hashlib.sha256(output.read_bytes()).hexdigest();output2,_=export_word(source,root/'out',{'include_review_appendix':True})
    check('no overwrite',output!=output2 and hashlib.sha256(output.read_bytes()).hexdigest()==hashout)
    check('appendix opt in',inspect_docx(output2)['images']==2)
    with zipfile.ZipFile(output) as z:
        doc=ET.fromstring(z.read('word/document.xml'))
        check('math structures',all(doc.findall('.//m:'+tag,NS) for tag in ['f','rad','sSubSup']))
        check('links and lists',bool(doc.findall('.//w:hyperlink',NS)) and len(doc.findall('.//w:numPr',NS))==4)
        check('aspect ratio',all(abs(int(n.get('cx'))/int(n.get('cy'))-4)<.002 for n in doc.findall('.//wp:extent',NS)))
    for name,md,needle in [('missing','![图](missing.png)','missing.png'),('remote','![图](https://example.com/x.png)','https://example.com/x.png'),('unc',r'![图](<\\server\share\a.png>)','首版仅支持')]:
        p=inputs/(name+'.md');p.write_text(md,encoding='utf-8')
        try:export_word(p,root/'out');check(name,False)
        except UserError as exc:check(name,needle in str(exc) and not (root/'out'/p.with_suffix('.docx').name).exists())
    p=inputs/'unsupported.md';p.write_text(r'原始公式 $\unsupportedcommand{x}$ 仍然保留。',encoding='utf-8')
    o,t=export_word(p,root/'out');r=read_report(o)
    check('unsupported not silent',r['status']=='review' and bool(r['issues']) and '\\unsupportedcommand{x}' in t and r['formulas'][0]['expression']==r'\unsupportedcommand{x}')
    p=inputs/'structural.md';p.write_text('```md\n## 原文资产与核对图\n```\n\n正文提到 原文资产与核对图。\n\n原文资产与核对图\n------------------\n\n删除此段\n\n# 后记\n\n后记保留',encoding='utf-8')
    o,t=export_word(p,root/'out');check('real heading only and higher heading retained','删除此段' not in t and '后记保留' in t and '## 原文资产与核对图' in t)
    p=inputs/'raw.md';p.write_text('<img src="https://example.com/x.png">\n\n<!-- source-page: 3 -->',encoding='utf-8')
    o,t=export_word(p,root/'out');check('raw markup preserved never fetched',read_report(o)['status']=='review' and 'https://example.com/x.png' in t and '来源页：3' in t)
    (root/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    return checks

if __name__=='__main__':
    print(json.dumps(run(sys.argv[1] if len(sys.argv)>1 else Path(__file__).parent/'word-qa'),ensure_ascii=True,indent=2))
