"""Observed requirement comparisons survive intervening source inspection."""
import json
from dataclasses import replace

import pytest
from test_work_asset_tools import setup
from test_work_binary_read_guidance import prompt
from test_work_completion_phase import commit

from dsgpt.inference import ollama_input_estimate
from dsgpt.project_tools import ProjectAction
from dsgpt.work import visible_requirement_read


@pytest.mark.parametrize('damage', [None, 'corrupt', 'stale'])
def test_source_read_retains_only_verified_requirement(tmp_path, damage):
    store, work, tid, _ = setup(tmp_path)
    original = 'Implement a persistent Unicode task list.'
    with store.transaction() as db:
        db.execute('UPDATE work_tasks SET requirements=? WHERE id=?', (original, tid))
        work.specs.initialize(db, tid, original)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    commit(work, tid, ProjectAction(tool='write_file', path='a.py', content='x = 1\n',
                                   summary='Create'))
    commit(work, tid, ProjectAction(tool='read_requirements', requirement_id=1, summary='Compare'))
    if damage:
        with store.transaction() as db:
            if damage == 'stale':
                db.execute('UPDATE work_tasks SET requirements=? WHERE id=?', ('Changed', tid))
            else:
                row = db.execute('SELECT result FROM work_steps WHERE task_id=? AND step=2',
                                 (tid,)).fetchone()
                result = json.loads(row['result'])
                result['content'] = 'Corrupt'
                db.execute('UPDATE work_steps SET result=? WHERE task_id=? AND step=2',
                           (json.dumps(result), tid))
    commit(work, tid, ProjectAction(tool='read_file', path='a.py', summary='Inspect'))
    model = replace(work.models['local'], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    assert visible_requirement_read(messages, original if damage != 'stale' else 'Changed') == (
        None if damage else (1, 0))
    latest = json.loads(messages[-1]['content'].removeprefix('Recorded tool result: '))
    assert latest['content'] == 'x = 1\n'
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    tight = prompt(store, work, tid, replace(model, context=2400, output_tokens=512))
    assert visible_requirement_read(tight, original) is None


def test_source_inspection_keeps_comparison_source_when_adding_requirement(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    original = 'Implement persistent tasks with Unicode titles. ' * 20
    with store.transaction() as db:
        db.execute('UPDATE work_tasks SET requirements=? WHERE id=?', (original, tid))
        work.specs.initialize(db, tid, original)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    for path in ('other.py', 'current.py'):
        commit(work, tid, ProjectAction(tool='write_file', path=path,
                                       content='# ' + path + '\n' + 'x = 1\n' * 80,
                                       summary='Create'))
    commit(work, tid, ProjectAction(tool='read_file', path='other.py', summary='Inspect'))
    commit(work, tid, ProjectAction(tool='read_requirements', requirement_id=1, summary='Compare'))
    commit(work, tid, ProjectAction(tool='read_file', path='current.py', summary='Inspect'))
    observed_comparison = False
    for size in range(7000, 15001, 100):
        model = replace(work.models['local'], context=size, output_tokens=512)
        messages = prompt(store, work, tid, model)
        if visible_requirement_read(messages, original) != (1, 0):
            continue
        latest = json.loads(messages[-1]['content'].removeprefix('Recorded tool result: '))
        assert latest['path'] == 'current.py'
        assert ollama_input_estimate(messages) + model.output_tokens <= model.context
        sources = [x['content'] for x in messages
                   if x['content'].startswith('Previous source page')]
        assert sources
        page = json.loads(sources[0][sources[0].index('{'):])
        assert page['path'] == 'other.py'
        assert page['content'] == '# other.py\n' + 'x = 1\n' * 80
        observed_comparison = True
    assert observed_comparison


@pytest.mark.parametrize('corrupt', [False, True])
def test_section_comparison_retains_verified_previous_section(tmp_path, corrupt):
    from dsgpt.work import RETAINED_REQUIREMENT_PREFIX
    from dsgpt.work_specs import CHUNK_BYTES
    store, work, tid, _ = setup(tmp_path)
    original = 'a' * CHUNK_BYTES + 'b' * 500
    with store.transaction() as db:
        db.execute('UPDATE work_tasks SET requirements=? WHERE id=?', (original, tid))
        work.specs.initialize(db, tid, original)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    commit(work, tid, ProjectAction(tool='read_requirements', requirement_id=2, summary='Read'))
    if corrupt:
        with store.transaction() as db:
            row = db.execute('SELECT result FROM work_steps WHERE task_id=?', (tid,)).fetchone()
            result = json.loads(row['result'])
            result['content'] = 'invented'
            db.execute('UPDATE work_steps SET result=? WHERE task_id=?', (json.dumps(result), tid))
    commit(work, tid, ProjectAction(tool='read_requirements', requirement_id=1, summary='Compare'))
    model = replace(work.models['local'], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    retained = [json.loads(m['content'][len(RETAINED_REQUIREMENT_PREFIX):]) for m in messages
                if m['content'].startswith(RETAINED_REQUIREMENT_PREFIX)]
    assert bool(retained) is not corrupt
    guidance = json.loads(messages[1]['content'])['next_step']
    assert 'do not alternate rereading them' in guidance
    assert 'only for missing text' in guidance
    if retained:
        assert retained[0]['requirement_id'] == 2
        assert retained[0]['content'] == 'b' * 500
    latest = json.loads(messages[-1]['content'].removeprefix('Recorded tool result: '))
    assert latest['requirement_id'] == 1
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
