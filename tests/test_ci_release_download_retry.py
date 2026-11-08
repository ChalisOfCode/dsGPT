"""Transient setup errors retry before bytes; integrity failures remain fatal."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest


@pytest.mark.parametrize('script', ['scan_public_source', 'prepare_complex_model_ci'])
def test_only_transient_open_errors_are_retried(script, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts' / (script + '.py')
    spec = importlib.util.spec_from_file_location(script, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sleep = Mock()
    monkeypatch.setattr(module.time, 'sleep', sleep)
    response = object()
    def error(code):
        return HTTPError('https://example.invalid/archive', code, 'failed', {}, None)
    opening = Mock(side_effect=[error(504), error(503), response])
    monkeypatch.setattr(module.urllib.request, 'urlopen', opening)
    assert module.open_release_download('https://example.invalid/archive') is response
    assert opening.call_count == 3
    assert [c.args for c in sleep.call_args_list] == [(1,), (2,)]
    opening.reset_mock(side_effect=True)
    opening.side_effect = [error(504)] * 3
    with pytest.raises(HTTPError):
        module.open_release_download('https://example.invalid/archive')
    assert opening.call_count == 3
    opening.reset_mock(side_effect=True)
    opening.side_effect = error(403)
    with pytest.raises(HTTPError):
        module.open_release_download('https://example.invalid/archive')
    assert opening.call_count == 1
