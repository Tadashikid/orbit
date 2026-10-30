import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Before any test imports registry/main: the tests run their own MCP servers on 8201-8205, so they never read or
# overwrite the statement uploaded to your running servers (run_servers.py on 8101-8105).
os.environ.setdefault("ORBIT_PORT_OFFSET", "100")
_TMP = tempfile.mkdtemp()  # audit log + sessions db: never data/session/
os.environ.setdefault("ORBIT_AUDIT_LOG", os.path.join(_TMP, "audit.jsonl"))
os.environ.setdefault("ORBIT_DB", os.path.join(_TMP, "orbit.db"))
os.environ.setdefault("ORBIT_DEMO_PASSWORD", secrets.token_urlsafe(16))  # a fresh demo login per run, for TestClient
ROOT = Path(__file__).resolve().parents[1]
PORTS = tuple(p + int(os.environ["ORBIT_PORT_OFFSET"]) for p in (8101, 8102, 8103, 8104, 8105, 8106))
SAMPLE = ROOT / "data" / "samples" / "manu_statement.csv"


def _open(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def statement(tmp_path_factory):
    """Manu's sample statement, masked exactly as an upload would be. Tests never touch data/session/."""
    sys.path.insert(0, str(ROOT / "backend"))
    from statement_import import mask_statement

    path = tmp_path_factory.mktemp("session") / "statement.csv"
    mask_statement(SAMPLE, path)
    return path


@pytest.fixture(scope="session")
def mcp_servers(statement):
    """Real MCP servers over HTTP, forced to seeded data and the sample statement."""
    assert not any(_open(p) for p in PORTS), f"ports {PORTS} are busy: the tests need their own MCP servers"
    env = {**os.environ, "ORBIT_OFFLINE": "1", "ORBIT_STATEMENT": str(statement),
           "ORBIT_CACHE_DIR": str(statement.parent),  # an empty search cache: seeded fares and prices only
           "ORBIT_HOLDS": str(statement.parent / "holds.json")}
    procs = [subprocess.Popen([sys.executable, str(p)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for p in sorted((ROOT / "mcp_servers").glob("*_server.py"))]
    deadline = time.time() + 20
    while not all(_open(p) for p in PORTS):
        assert time.time() < deadline, "MCP servers did not start"
        time.sleep(0.2)
    yield
    for p in procs:
        p.terminate()
