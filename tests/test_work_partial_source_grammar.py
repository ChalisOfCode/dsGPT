"""Displayed partial source remains usable without forcing a duplicate read."""
import hashlib
import json
from dataclasses import replace

import pytest
from test_work_asset_tools import setup
from test_work_binary_read_guidance import prompt
from test_work_completion_phase import commit

from dsgpt.inference import ollama_input_estimate
from dsgpt.project_tools import ProjectAction, action_schema, source_page
from dsgpt.work import RETAINED_SOURCE_PREFIX, visible_partial_source_pages


@pytest.mark.parametrize('damage', [None, 'stale', 'content', 'offset', 'empty', 'omitted'])
def test_partial_page_must_match_current_saved_bytes(damage):
    body = 'π = 1\n' * 800
    page = source_page({'content': body, 'sha256': hashlib.sha256(body.encode()).hexdigest()},
                       'module.py', 0)
    if damage == 'stale':
        body += '# changed'
    elif damage == 'content':
        page['content'] = 'corrupt'
    elif damage == 'offset':
        page['offset'] = -1
    elif damage == 'empty':
        page['content'] = ''
    messages = [] if damage == 'omitted' else [
        {'role': 'user', 'content': RETAINED_SOURCE_PREFIX + json.dumps(page)}]
    assert visible_partial_source_pages(messages, {'module.py': body}) == (
        {} if damage else {'module.py': {0}})


def test_schema_preserves_unseen_pages_other_paths_and_edits():
    schema = action_schema(file_paths=['a.py', 'b.py'], visible_read_pages={'a.py': {0, 30}})
    reads = [v for v in schema['oneOf'] if v['properties']['tool']['const'] == 'read_file']
    def allowed(path, offset=None):
        return any(v['properties']['path']['const'] == path
                   and (offset is not None or 'offset' not in v['required'])
                   and v['properties']['offset']['minimum'] <= (offset or 0)
                   <= v['properties']['offset']['maximum'] for v in reads)
    assert not allowed('a.py') and not allowed('a.py', 0) and not allowed('a.py', 30)
    assert all(allowed('a.py', i) for i in (1, 29, 31, 3000))
    assert allowed('b.py') and allowed('b.py', 0)
    assert any(v['properties']['tool']['const'] == 'edit_file' for v in schema['oneOf'])


def test_unmatched_edit_retains_partial_page_and_continuation(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(db, tid, 'Implement the module and test it.')
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    body = '# source\n' + 'value = 1\n' * 400
    digest = hashlib.sha256(body.encode()).hexdigest()
    commit(work, tid, ProjectAction(tool='write_file', path='module.py', content=body,
                                   summary='Create'))
    commit(work, tid, ProjectAction(tool='read_file', path='module.py', summary='Read'))
    commit(work, tid, ProjectAction(tool='edit_file', path='module.py', old_text='absent',
                                   new_text='replacement', expected_sha256=digest, summary='Edit'))
    model = replace(work.models['local'], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    assert visible_partial_source_pages(messages, {'module.py': body}) == {'module.py': {0}}
    latest = json.loads(messages[-1]['content'].removeprefix('Recorded tool result: '))
    assert latest['error'] == 'edit_match_not_unique' and latest['matches'] == 0
    assert 'next_offset' in latest['help']
    assert store.one('SELECT content FROM work_files WHERE task_id=?', (tid,))['content'] == body
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    tight = prompt(store, work, tid, replace(model, context=2500, output_tokens=512))
    assert visible_partial_source_pages(tight, {'module.py': body}) == {}
