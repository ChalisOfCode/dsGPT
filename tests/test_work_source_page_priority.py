"""Keep a continuation's observed prefix before more recent unrelated source."""
import hashlib
import json
from dataclasses import replace

import pytest
from test_work_asset_tools import setup
from test_work_binary_read_guidance import prompt
from test_work_completion_phase import commit

from dsgpt.inference import ollama_input_estimate
from dsgpt.project_tools import ProjectAction
from dsgpt.work import visible_partial_source_pages


@pytest.mark.parametrize('stale', [False, True])
def test_continuation_prioritizes_current_matching_prefix(tmp_path, stale):
    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(db, tid, 'Implement the module and test it.')
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    bodies = {'target.py': 'x = 1\n' * 550, 'other.py': 'y = 2\n' * 550}
    for path, body in bodies.items():
        commit(work, tid, ProjectAction(tool='write_file', path=path, content=body,
                                       summary='Create'))
    for path in bodies:
        commit(work, tid, ProjectAction(tool='read_file', path=path, summary='Inspect'))
    if stale:
        bodies['target.py'] += '# changed\n'
        digest = hashlib.sha256(bodies['target.py'].encode()).hexdigest()
        with store.transaction() as db:
            db.execute('UPDATE work_files SET content=?,sha256=? WHERE task_id=? AND path=?',
                       (bodies['target.py'], digest, tid, 'target.py'))
    commit(work, tid, ProjectAction(tool='read_file', path='target.py', offset=3000,
                                   summary='Continue'))
    found = False
    for size in range(9000, 16385, 100):
        model = replace(work.models['local'], context=size, output_tokens=4096)
        messages = prompt(store, work, tid, model)
        pages = visible_partial_source_pages(messages, bodies)
        if stale:
            assert 'target.py' not in pages
        sources = [json.loads(m['content'][m['content'].index('{'):]) for m in messages
                   if m['content'].startswith('Previous source page')]
        if len(sources) == 1:
            assert sources[0]['path'] == ('other.py' if stale else 'target.py')
            assert ollama_input_estimate(messages) + model.output_tokens <= model.context
            latest = json.loads(messages[-1]['content'].removeprefix('Recorded tool result: '))
            assert latest['offset'] == 3000 and latest['content'] == bodies['target.py'][3000:]
            found = True
            break
    assert found
