"""Сборка статьи с русскими переносами без изменения установленной TeX-системы."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile

ARTICLE = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, logfile, **kwargs):
    with logfile.open('w') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, **kwargs)
    if result.returncode:
        tail = '\n'.join(logfile.read_text(errors='replace').splitlines()[-20:])
        raise RuntimeError(f'Command failed ({result.returncode}): {tail}')


def main():
    build = Path(tempfile.mkdtemp(prefix='pnd-edit-', dir='/private/tmp'))
    fmt = build / 'format'
    fmt.mkdir()
    (fmt / 'language.dat').write_text(
        'english hyphen.tex\n=usenglish\n=USenglish\n=american\nrussian loadhyph-ru.tex\n')
    env = dict(os.environ, TEXINPUTS=str(fmt) + os.pathsep + os.environ.get('TEXINPUTS', ''))
    run(['pdftex', '-ini', '-etex', '-jobname=pndpdflatex', '-progname=pdflatex', 'pdflatex.ini'],
        fmt / 'format-build.txt', cwd=fmt, env=env)
    env = dict(os.environ, TEXFORMATS=str(fmt) + os.pathsep)
    inputs = sorted(list(ARTICLE.glob('*.tex')) + list((ARTICLE / 'sections').glob('*.tex'))
                    + list(ARTICLE.glob('*.sty')) + list((ARTICLE / 'Figure').glob('*.pdf')))
    before = {str(p.relative_to(ARTICLE)): digest(p) for p in inputs}
    results = {}
    for stem in ['main']:
        out = build / stem
        out.mkdir()
        previous = None
        for i in range(1, 5):
            run(['pdflatex', '-fmt=pndpdflatex', f'-jobname={stem}',
                 '-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
                 f'-output-directory={out}', f'{stem}.tex'],
                out / f'pass-{i}.txt', cwd=ARTICLE, env=env)
            current = digest(out / f'{stem}.aux')
            if current == previous:
                break
            previous = current
        else:
            raise RuntimeError('References did not stabilize in four passes')
        log = (out / f'{stem}.log').read_text(errors='replace')
        invalid = re.findall(
            r'LaTeX Warning: (?:Reference|Citation)[\s\S]*?undefined[^\n]*'
            r'|LaTeX Warning: There were undefined[^\n]*'
            r'|LaTeX Warning: Label[^\n]*multiply defined[^\n]*'
            r'|LaTeX Warning: There were multiply-defined[^\n]*', log)
        if invalid or 'No hyphenation patterns' in log:
            raise RuntimeError('Reference or Russian hyphenation check failed: ' + '\n'.join(invalid))
        pdf = out / f'{stem}.pdf'
        info = subprocess.run(['pdfinfo', str(pdf)], capture_output=True, text=True, check=True).stdout
        pages = int(re.search(r'^Pages:\s+(\d+)', info, re.MULTILINE).group(1))
        if stem == 'main' and pages > 25:
            raise RuntimeError(f'Article exceeds 25 pages: {pages}')
        results[stem] = {'pages': pages, 'passes': i, 'reference_warnings': 0,
                         'russian_hyphenation': True, 'overfull_boxes': log.count('Overfull'),
                         'sha256': digest(pdf)}
    after = {str(p.relative_to(ARTICLE)): digest(p) for p in inputs}
    if before != after:
        raise RuntimeError('Sources changed during build; PDFs were not copied')
    for stem in results:
        shutil.copy2(build / stem / f'{stem}.pdf', ARTICLE / f'{stem}.pdf')
    report = {'sources': before, 'outputs': results}
    (ARTICLE / '_analysis').mkdir(exist_ok=True)
    (ARTICLE / '_analysis/build_check.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Build directory:', build)
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
