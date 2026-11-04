import io
import json
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import pair

from dsgpt import search_service, tool_setup
from dsgpt.builds import WorkBuilds
from dsgpt.sandbox import SandboxError
from dsgpt.storage import Store
from dsgpt.tool_image import DOCKERFILE


def test_bundled_tool_recipe_matches_reviewed_file():
    assert DOCKERFILE == Path("execution/Dockerfile").read_text()


def test_setup_endpoints_are_owner_only(backend):
    phone, _ = pair(backend, ["chat", "work"])
    headers = {"Authorization": "Bearer " + phone["token"]}
    for path in ["/v1/tools/setup", "/v1/search/service"]:
        assert backend.client.get(path, headers=headers).status_code == 403
        assert backend.client.get(path).status_code == 200
    for path in [f"/v1/tools/setup/{uuid4()}", f"/v1/search/service/start/{uuid4()}"]:
        assert backend.client.post(path, headers=headers).status_code == 403


class ImageTransport:
    owner = None
    unowned = False
    fail = False
    calls = []

    def __init__(self, directory, image, owner):
        self.owner = owner

    async def cli(self, args, **kwargs):
        self.calls.append(args)
        if args[:2] == ["image", "inspect"]:
            return (
                (0, json.dumps([{"Config": {"Labels": {"org.dsgpt.owner": "other"}}}]), "", False)
                if self.unowned
                else (1, b"", b"", False)
            )
        if args[0] == "build":
            with tarfile.open(fileobj=io.BytesIO(kwargs["data"])) as archive:
                assert set(archive.getnames()) == set(tool_setup.recipe_files())
                assert archive.extractfile("Dockerfile").read().decode() == DOCKERFILE
            return int(self.fail), b"build log", b"", False
        raise AssertionError(args)

    async def checked(self, args, **kwargs):
        return json.dumps(
            [
                {
                    "Id": "sha256:" + "a" * 64,
                    "Config": {
                        "Labels": {
                            "org.dsgpt.owner": self.owner,
                            "org.dsgpt.recipe": tool_setup.recipe_digest(),
                        }
                    },
                }
            ]
        )


@pytest.mark.parametrize("failure", [None, "unowned", "fail"])
async def test_tool_setup_idempotency_ownership_and_failure(tmp_path, monkeypatch, failure):
    ImageTransport.calls = []
    monkeypatch.setattr(ImageTransport, "unowned", failure == "unowned")
    monkeypatch.setattr(ImageTransport, "fail", failure == "fail")
    monkeypatch.setattr(tool_setup, "DockerSandbox", ImageTransport)
    store = Store(tmp_path)
    builds = WorkBuilds(store)

    async def probe():
        builds.ready = True

    monkeypatch.setattr(builds, "probe", probe)
    setup = tool_setup.ToolSetup(store, builds)
    identifier = str(uuid4())
    first = setup.start(identifier)
    assert setup.start(identifier) == first
    await setup.worker
    job = setup.start(identifier)
    assert job["status"] == ("failed" if failure else "completed")
    assert sum(call[0] == "build" for call in ImageTransport.calls) == (
        0 if failure == "unowned" else 1
    )
    assert builds.ready == (failure is None)


def search_container(owner):
    return {
        "Config": {
            "Labels": {"org.dsgpt.owner": owner, "org.dsgpt.purpose": "local-search"},
            "Image": search_service.IMAGE,
            "User": "977:977",
            "Entrypoint": ["/usr/local/searxng/.venv/bin/python"],
            "Cmd": ["-c", search_service.PROGRAM],
        },
        "HostConfig": {
            "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8888"}]},
            "ReadonlyRootfs": True,
            "NetworkMode": "bridge",
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Memory": 1073741824,
            "MemorySwap": 1073741824,
            "NanoCpus": 1000000000,
            "PidsLimit": 128,
        },
        "Mounts": [],
    }


@pytest.mark.parametrize("mutation", ["owner", "bind", "port", "command", "privileged", "writable"])
def test_search_service_rejects_replaced_container(tmp_path, mutation):
    service = search_service.SearchService(Store(tmp_path), None)
    value = search_container(service.owner)
    service.validate(value)
    if mutation == "owner":
        value["Config"]["Labels"]["org.dsgpt.owner"] = "other"
    if mutation == "bind":
        value["HostConfig"]["Binds"] = ["/private:/private"]
    if mutation == "port":
        value["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostIp"] = "0.0.0.0"
    if mutation == "command":
        value["Config"]["Cmd"] = ["-c", "other"]
    if mutation == "privileged":
        value["HostConfig"]["Privileged"] = True
    if mutation == "writable":
        value["HostConfig"]["ReadonlyRootfs"] = False
    with pytest.raises(SandboxError, match="ownership_mismatch"):
        service.validate(value)


async def test_recovery_does_not_replay_uncertain_installations(tmp_path):
    store = Store(tmp_path)
    with store.transaction() as db:
        db.execute("INSERT INTO tool_setup_jobs VALUES('a','running','','',NULL,NULL,'')")
        db.execute("INSERT INTO search_service_jobs VALUES('b','start','running','','',NULL)")
    tool_setup.ToolSetup(store, WorkBuilds(store)).recover()
    search_service.SearchService(store, None).recover()
    assert store.one("SELECT status FROM tool_setup_jobs")["status"] == "interrupted"
    assert store.one("SELECT status FROM search_service_jobs")["status"] == "interrupted"
