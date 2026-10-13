"""Deferred original prompts: immutable input and script-bound visual selections."""
import copy
import hashlib
import previs as core
import repair_prompt


def text_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def register(p, project, gid, text):
    core.require(isinstance(text, str) and text.strip(), 'Original prompt must be nonempty text')
    from storyboard_inputs import context
    row = dict(source_fingerprint=context(p, project, gid)['source_fingerprint'],
               text=text, text_sha256=text_sha(text))
    p.setdefault('source_storyboard_prompts', {})[gid] = row
    return row


def current(p, gid):
    source = p.get('source_storyboard_prompts', {}).get(gid)
    if source is None: return None
    return dict(source=copy.deepcopy(source), assessment=copy.deepcopy(p.get('repair_prompt_references', {}).get(gid)))


def validate(snapshot, binding, originals, shot_ids):
    """Validate provenance/structure; semantic compatibility remains an agent judgment."""
    if snapshot is None:
        return {}
    errors = []
    def check(ok, message):
        if not ok:
            errors.append('Original prompt reference: ' + message)
    core.require(isinstance(snapshot, dict), 'Original prompt reference must be an object')
    source, review = snapshot.get('source'), snapshot.get('assessment')
    core.require(isinstance(source, dict) and isinstance(review, dict),
                 'Original prompt needs one batch repair_prompt_references assessment before repair')
    raw = source.get('text')
    core.require(isinstance(raw, str) and raw.strip(), 'Original prompt text required')
    check(source.get('text_sha256') == text_sha(raw), 'text SHA256 mismatch')
    source_key = 'source_fingerprint'
    check(source.get(source_key) == binding[source_key],
          'wrong or changed source images')
    check(review.get('source_sha256') == text_sha(raw), 'stale prompt assessment')
    check(review.get(source_key) == binding[source_key], 'assessment source mismatch')
    check(review.get('script_fingerprint') == binding['script_fingerprint'], 'stale script assessment')
    check(review.get('preserves_story') is True, 'preserves_story=true required')
    for field in ('compatibility_reason',):
        check(isinstance(review.get(field), str) and bool(review[field].strip()),
              field + ' required: check actors, order, results, timing, aspect and silent rules')
    selections, excluded = review.get('selections'), review.get('excluded')
    core.require(isinstance(selections, list) and isinstance(excluded, list), 'selections/excluded arrays required')
    check(bool(selections or excluded), 'select compatible details or explain why none can be used')
    guidance = {}
    for i, row in enumerate(selections):
        if not isinstance(row, dict):
            check(False, f'selections[{i}] must be an object')
            continue
        sid = row.get('shot_id')
        valid_sid = isinstance(sid, str) and sid in shot_ids
        check(valid_sid, f'selections[{i}] must refer to this source group')
        for key, source_text in [('source_quote', raw),
                                 ('script_quote', originals[sid]['text'] if valid_sid else '')]:
            value = row.get(key)
            check(isinstance(value, str) and bool(value.strip()) and value in source_text,
                  f'selections[{i}].{key} must be an exact source excerpt')
        text = row.get('visual_text')
        valid_text = isinstance(text, str) and bool(text.strip())
        check(valid_text, f'selections[{i}].visual_text required')
        if valid_text:
            check(not repair_prompt.speech_signals(text) and not any(t in text for t in repair_prompt.TAGS),
                  f'selections[{i}] contains speech/audio/text or shot headers')
            if valid_sid:
                check(text not in guidance.get(sid, []), f'{sid}: duplicate selected guidance')
                guidance.setdefault(sid, []).append(text)
    for i, row in enumerate(excluded):
        if not isinstance(row, dict):
            check(False, f'excluded[{i}] must be an object')
            continue
        quote, reason = row.get('source_quote'), row.get('reason')
        check(isinstance(quote, str) and bool(quote.strip()) and quote in raw,
              f'excluded[{i}].source_quote must be an exact excerpt')
        check(isinstance(reason, str) and bool(reason.strip()), f'excluded[{i}].reason required')
    repair_prompt.finish(errors)
    return guidance
