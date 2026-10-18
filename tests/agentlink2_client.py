"""Independent synthetic agent: one SDK session and one existing MCP connector."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import subprocess

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nodelang.application_machine_transport import _MAX_MESSAGE_BYTES


class AgentClient:
    def __init__(self, process):
        self.process = process

    async def call_tool(self, name, arguments, *, meta=None):
        request = json.dumps({"name": name, "arguments": arguments, "meta": meta}) + "\n"
        self.process.stdin.write(request.encode("utf-8"))
        await self.process.stdin.drain()
        line = await self.process.stdout.readline()
        if not line:
            raise RuntimeError("independent agent process ended before its reply")
        return CallToolResult.model_validate_json(line)


@asynccontextmanager
async def start_agent(environment):
    process = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).resolve()),
        cwd=str(Path(__file__).resolve().parents[1]), env=environment,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        limit=4 * _MAX_MESSAGE_BYTES,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        assert json.loads(await process.stdout.readline()) == {"ready": True}
        yield AgentClient(process)
    finally:
        process.stdin.close()
        assert await process.wait() == 0


async def run_agent():
    parameters = StdioServerParameters(command=sys.executable,
        args=["-m", "nodelang.native_agent_mcp"], cwd=str(Path(__file__).resolve().parents[1]))
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            print(json.dumps({"ready": True}), flush=True)
            while line := await asyncio.to_thread(sys.stdin.readline):
                request = json.loads(line)
                result = await client.call_tool(request["name"], request["arguments"], meta=request["meta"])
                print(result.model_dump_json(), flush=True)


if __name__ == "__main__":
    asyncio.run(run_agent())
