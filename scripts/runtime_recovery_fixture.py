"""TEST ONLY: local TCP fixture for an execution host denying UDS and /proc socket reads.

Not installed in the backend wheel. Never use this entry point with user data.
It intentionally substitutes the listener ownership check, and cannot validate
the production Windows check or Linux private socket boundary.
"""

import argparse
import hashlib
from pathlib import Path

import uvicorn

import dsgpt.api
from dsgpt.config import Settings
from dsgpt.runtime import ManagedInference
from dsgpt.storage import utcnow


class TestTCPInference(ManagedInference):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.socket_path = None

    def owns_listener(self):
        return self.child is not None and self.child.poll() is None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--work-reference-fixture", action="store_true")
    args = parser.parse_args()
    dsgpt.api.ManagedInference = TestTCPInference
    app = dsgpt.api.create_app(Settings(args.data_dir))
    if args.work_reference_fixture:

        class ReferenceReader:
            async def read(self, url):
                assert url == "https://example.org/dsgpt-fixture"
                text = "The reference marker is AMBER."
                return {
                    "url": url,
                    "final_url": url,
                    "title": "Synthetic reference fixture",
                    "text": text,
                    "links": [],
                    "retrieved_at": utcnow(),
                    "published_at": None,
                    "text_truncated": False,
                    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }

        app.state.work.references.reader = ReferenceReader()
    uvicorn.run(app, host="127.0.0.1", port=18765, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
