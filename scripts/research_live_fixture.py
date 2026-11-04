"""TEST ONLY: restricted-host substitutions for public research and local inference."""

import argparse
import os
import ssl
from pathlib import Path

import httpx
import uvicorn
from runtime_recovery_fixture import TestTCPInference

import dsgpt.api
from dsgpt.config import Settings
from dsgpt.web_retrieval import PublicReader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--search-origin")
    args = parser.parse_args()
    dsgpt.api.ManagedInference = TestTCPInference
    app = dsgpt.api.create_app(Settings(args.data, search_origin=args.search_origin))
    app.state.research.reader = PublicReader(
        lambda: httpx.AsyncHTTPTransport(
            proxy=os.environ["HTTPS_PROXY"],
            verify=ssl.create_default_context(),
        )
    )
    uvicorn.run(app, host="127.0.0.1", port=18765, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
