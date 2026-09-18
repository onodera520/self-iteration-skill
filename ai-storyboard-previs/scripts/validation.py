"""Read-only, dependency-aware diagnostics. Never relax mutation safety gates."""
from __future__ import annotations


class ValidationError(ValueError):
    def __init__(self, errors, blocked):
        self.errors = list(errors)
        self.blocked = list(blocked)
        lines = [f"Project validation: {len(errors)} error(s), {len(blocked)} blocked check(s)"]
        lines += [f"ERROR {r['path']}: {r['message']}" for r in errors]
        lines += [f"BLOCKED {r['path']}: {r['message']}" for r in blocked]
        super().__init__("\n".join(lines))


class Report:
    def __init__(self):
        self.errors = []
        self.blocked = []

    def check(self, condition, path, message):
        if not condition:
            row = dict(path=path, message=message)
            if row not in self.errors:
                self.errors.append(row)
        return bool(condition)

    def block(self, path, message):
        row = dict(path=path, message=message)
        if row not in self.blocked:
            self.blocked.append(row)

    def kind(self, value, cls, path):
        names = {dict: 'object', list: 'array', str: 'string'}
        return self.check(isinstance(value, cls), path,
                          f"expected {names.get(cls, cls.__name__)}, got {type(value).__name__}")

    def finish(self):
        if self.errors or self.blocked:
            raise ValidationError(self.errors, self.blocked)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def text_array(value):
    return isinstance(value, list) and all(text(x) for x in value)


def sourced(value, kinds=('script', 'asset', 'inference')):
    return isinstance(value, dict) and value.get('kind') in kinds and text(value.get('ref'))


def shot_path(shot, index):
    sid = shot.get('id') if isinstance(shot, dict) else None
    return f"shots[{sid}]" if text(sid) else f"shots[{index}]"


def style_shape(p, report):
    """Optional preparation data only. Current SHA256 equality remains a use-time gate."""
    if 'repair_asset_style' not in p:
        return
    base = 'repair_asset_style'
    profile = p[base]
    if not report.kind(profile, dict, base):
        return
    report.check(profile.get('preserves_story') is True, base + '.preserves_story',
                 'Style guidance must preserve script and narrative-first tolerance')
    rows = profile.get('assets')
    if not report.kind(rows, list, base + '.assets'):
        return
    for i, row in enumerate(rows):
        path = f'{base}.assets[{i}]'
        if not report.kind(row, dict, path):
            continue
        report.check(text(row.get('asset_id')), path + '.asset_id', 'asset ID required')
        report.check(text(row.get('sha256')), path + '.sha256', 'current asset SHA256 required')
        facts = row.get('visible_style_facts')
        report.check(text_array(facts) and bool(facts), path + '.visible_style_facts',
                     'Visible asset style facts required as nonempty text array; do not infer style from the failed video')
        report.check(text(row.get('guidance')), path + '.guidance', 'Grounded asset style guidance required')
