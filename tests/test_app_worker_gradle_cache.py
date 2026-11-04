"""Keep prepared-host cache reuse compatible with the isolated build recipe."""

from pathlib import Path

import pytest

from dsgpt import app_build_worker


class CommandCaptured(Exception):
    pass


@pytest.mark.parametrize("shared", [False, True])
def test_android_gradle_uses_distinct_read_only_cache_only(tmp_path, monkeypatch, shared):
    monkeypatch.chdir(tmp_path)
    android = tmp_path / "android"
    (android / "app").mkdir(parents=True)
    (android / "app/build.gradle").write_text("// fixture\n")
    prepared = tmp_path / "prepared-cache"
    (prepared / "caches/modules-2").mkdir(parents=True)
    (prepared / "caches/modules-2/dependency").write_bytes(b"prepared dependency")
    (prepared / "caches/gradle-metadata").write_bytes(b"metadata")
    monkeypatch.setenv("DSGPT_GRADLE_CACHE", str(prepared))
    monkeypatch.setenv("GRADLE_RO_DEP_CACHE", "inherited-cache-must-not-leak")
    user = tmp_path / ".gradle-user"
    if shared:
        user.symlink_to(prepared, target_is_directory=True)
    calls = []

    def capture(argv, **kwargs):
        calls.append((argv, kwargs))
        raise CommandCaptured

    monkeypatch.setattr(app_build_worker, "run", capture)
    with pytest.raises(CommandCaptured):
        app_build_worker.android_build()
    argv, kwargs = calls[0]
    assert argv[1:3] == ["--offline", "--no-daemon"]
    assert kwargs["cwd"] == android
    env = kwargs["env"]
    assert Path(env["GRADLE_USER_HOME"]).resolve() == user.resolve()
    assert (prepared / "caches/modules-2/dependency").read_bytes() == b"prepared dependency"
    if shared:
        assert "GRADLE_RO_DEP_CACHE" not in env
        assert user.is_symlink()
    else:
        assert Path(env["GRADLE_RO_DEP_CACHE"]) == prepared / "caches"
        assert (user / "caches/gradle-metadata").read_bytes() == b"metadata"
        assert not (user / "caches/modules-2").exists()
