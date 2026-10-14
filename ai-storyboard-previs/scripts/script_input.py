"""Extract numbered, labelled shot blocks without rewriting source text."""
from __future__ import annotations
import re
from pathlib import Path

import previs as core
from evidence_runtime import evidence_operation
from validation import Report, text

HEADER = re.compile(r'(?m)^[ \t]*镜头[ \t]*(\d+)(?=[ \t,，。:：;；\r\n【]|$)')
FIELD = re.compile(r'【(时长|镜头设计|镜头内容)】')
DURATION = re.compile(r'\s*(\d+(?:\.\d+)?)\s*(?:秒|[sS])\s*[,，。.;；:：]?\s*')


def parse(source, source_name='脚本'):
    report = Report()
    core.require(text(source), '脚本须为非空 UTF-8 文本')
    headers = list(HEADER.finditer(source))
    core.require(headers, '未找到行首镜头编号；支持“镜头N”及【时长】【镜头设计】【镜头内容】')
    numbers = [int(h[1]) for h in headers]
    report.check(numbers[0] > 0 and numbers == list(range(numbers[0], numbers[0] + len(numbers))),
                 'script.shot_numbers', '镜号须为连续递增的正整数，不得重复、缺号或重排')
    shots = []
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(source)
        block = source[header.start():end].strip()
        sid = f'S{numbers[i]:02d}'
        where = f'{source_name}:镜头{numbers[i]}（行{source.count(chr(10), 0, header.start()) + 1}）'
        fields = list(FIELD.finditer(block))
        if not report.check([m[1] for m in fields] == ['时长', '镜头设计', '镜头内容'], where,
                            '须依次包含一次【时长】【镜头设计】【镜头内容】；不按非空行数拆镜'):
            continue
        values = [block[m.end():fields[j + 1].start() if j + 1 < len(fields) else len(block)]
                  for j, m in enumerate(fields)]
        duration = DURATION.fullmatch(values[0])
        valid = report.check(duration is not None, where + '.时长', '须为正秒数，允许 s／秒及逗号、句号、空白分隔')
        seconds = float(duration[1]) if duration else 0
        valid = report.check(core.number(seconds) and seconds > 0, where + '.时长', '计划时长须为有限正数') and valid
        for name, value in zip(('镜头设计', '镜头内容'), values[1:]):
            valid = report.check(text(value), where + '.' + name, '字段内容不能为空') and valid
        if valid:
            shots.append(dict(id=sid, script=block, duration=int(seconds) if seconds.is_integer() else seconds,
                              duration_source=dict(kind='script', ref=f'{source_name}：镜头{numbers[i]}【时长】'),
                              shot_design=values[1].strip()))
    report.finish()
    return shots


def extract(script_file, supplied, output, *, image_base=None):
    """Write a mechanical INPUT draft; explicit narrative judgments are filled later."""
    with evidence_operation():
        output = Path(output).resolve()
        core.require(output.parent.is_dir(), 'INPUT 父目录须已存在；请使用独立的内部目录')
        core.require(not output.exists() and output != Path(script_file).resolve(), '不要覆盖已有 INPUT 或原脚本')
        data = read_input(script_file, supplied, image_base=image_base or output.parent)
    # Persist the draft only after all source checks, including the final rehash.
    with core.locked(output):
        core.require(not Path(output).exists(), '不要覆盖已有 INPUT')
        core.save(output, data)
    return dict(input=str(output), shots=len(data['shots']), duration=sum(s['duration'] for s in data['shots']),
                next_action='仅提取原文、时长和图片对应；同批补齐原资产及逐镜必要判断后再 prepare。')


def read_input(script_file, supplied, *, image_base):
    """Read raw source and ordered correspondence; no image decoding or output."""
    script_file = Path(script_file).resolve()
    # Byte decoding preserves CRLF and BOM handling; universal-newline reads would change excerpts.
    payload = script_file.read_bytes()
    import hashlib
    core.require(core.sha(script_file) == hashlib.sha256(payload).hexdigest(), '提取时脚本已变化，请重试')
    source = payload.decode('utf-8-sig')
    shots = parse(source, script_file.name)
    report = Report()
    if report.kind(supplied, list, 'images'):
        report.check(len(supplied) == len(shots), 'images',
                     f'图片数量与脚本镜头数量不一致：{len(supplied)} 张／{len(shots)} 镜')
        base = Path(image_base).resolve()
        for i, row in enumerate(supplied):
            where = f'images[{i}]'
            if isinstance(row, dict):
                report.check(i < len(shots) and row.get('shot_id') == shots[i]['id'], where + '.shot_id',
                             '镜号／顺序须与脚本一致，不自动排序或重新匹配')
                value = row.get('path')
            else:
                value = row
            if report.check(text(value), where + '.path', '须为原图路径或 shot_id/path 对应项'):
                path = (base / value).resolve()
                report.check(path.is_file(), where + '.path', f'原图不存在：{path}')
                if i < len(shots):
                    shots[i]['image'] = str(path)
    report.finish()
    return dict(input_version=1, title=script_file.stem, source_script=source, assets=[], shots=shots)
