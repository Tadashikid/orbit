"""Start every MCP server in mcp_servers/ (Ctrl+C stops them all).

    .venv\\Scripts\\python run_servers.py
calendar :8101 · gmail :8102 · finance :8103 · travel :8104, each at http://127.0.0.1:<port>/mcp
"""
import subprocess
import sys
from pathlib import Path

servers = sorted((Path(__file__).parent / "mcp_servers").glob("*_server.py"))
procs = [subprocess.Popen([sys.executable, str(s)]) for s in servers]
print("started:", ", ".join(s.stem for s in servers), flush=True)
try:
    for p in procs:
        p.wait()
except KeyboardInterrupt:
    for p in procs:
        p.terminate()
