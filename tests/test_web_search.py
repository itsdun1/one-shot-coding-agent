import asyncio
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.tools import tool

search = importlib.import_module("agent.tools.web_search")
parallel = importlib.import_module("agent.tools.parallel_search")


@pytest.fixture
def parallel_server(monkeypatch):
    pytest.importorskip("mcp")
    calls = []
    payload = {
        "results": [
            {"url": "https://example.com/docs", "title": "API docs", "excerpts": ["Use v2."]},
            {"url": "https://example.com/guide", "title": "Guide", "excerpts": ["Migration guide"]},
        ]
    }
    state = {"payload": payload, "isError": False, "wait": False, "status": 200}
    started = asyncio.Event()

    async def handle(request):
        calls.append(request)
        assert str(request.url) == parallel.PARALLEL_MCP_URL
        assert request.headers["user-agent"] == parallel.PARALLEL_USER_AGENT
        assert "authorization" not in request.headers
        if request.method != "POST":
            return httpx.Response(405)
        message = json.loads(request.content)
        method = message["method"]
        if method.startswith("notifications/"):
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-parallel", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": []}
        else:
            assert method == "tools/call"
            assert message["params"]["name"] == "web_search"
            assert message["params"]["arguments"] == {
                "objective": "current API docs",
                "search_queries": ["current API docs"],
            }
            started.set()
            if state["wait"]:
                await asyncio.Event().wait()
            if state["status"] != 200:
                return httpx.Response(state["status"], text="Provider unavailable")
            result = {
                "content": [{"type": "text", "text": json.dumps(state["payload"])}],
                "isError": state["isError"],
            }
            if not state.get("text_only"):
                result["structuredContent"] = state["payload"]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    clients = []

    def client_factory(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(parallel, "httpx", SimpleNamespace(AsyncClient=client_factory))
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "parallel")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    return SimpleNamespace(calls=calls, state=state, started=started, clients=clients)


@pytest.mark.parametrize("include_contents", [True, False])
def test_parallel_registered_tool_path(parallel_server, include_contents):
    # The same exported function is passed to create_deep_agent in server.py.
    from agent.tools import web_search

    result = tool(web_search).invoke(
        {"query": "current API docs", "num_results": 1, "include_contents": include_contents}
    )

    assert result["success"] is True
    assert result["error"] is None
    entries = json.loads(result["results"])
    assert len(entries) == 1
    assert entries[0]["url"] == "https://example.com/docs"
    assert ("excerpts" in entries[0]) is include_contents
    assert parallel_server.calls
    assert all(client.is_closed for client in parallel_server.clients)


def test_parallel_text_result(parallel_server):
    parallel_server.state["text_only"] = True
    result = search.web_search("current API docs")
    assert result["success"] is True
    assert json.loads(result["results"])[0]["excerpts"] == ["Use v2."]


@pytest.mark.parametrize("failure", ["tool", "http", "malformed"])
def test_parallel_errors_return_existing_envelope(parallel_server, failure):
    if failure == "tool":
        parallel_server.state.update(isError=True, payload={"error": "quota reached"})
    elif failure == "http":
        parallel_server.state["status"] = 503
    else:
        parallel_server.state["payload"] = {"unexpected": []}

    result = search.web_search("current API docs")

    assert result["success"] is False
    assert result["results"] is None
    assert result["error"]
    if failure == "tool":
        assert "quota reached" in result["error"]
    assert all(client.is_closed for client in parallel_server.clients)


def test_parallel_timeout(parallel_server, monkeypatch):
    parallel_server.state["wait"] = True
    monkeypatch.setattr(parallel, "PARALLEL_SEARCH_TIMEOUT", 0.05)

    result = search.web_search("current API docs")

    assert result["success"] is False
    assert "TimeoutError" in result["error"]
    assert all(client.is_closed for client in parallel_server.clients)


async def test_parallel_cancellation(parallel_server):
    parallel_server.state["wait"] = True
    task = asyncio.create_task(parallel.search_parallel("current API docs", 5, True))
    await asyncio.wait_for(parallel_server.started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(client.is_closed for client in parallel_server.clients)


def test_parallel_requires_extra(monkeypatch):
    import sys

    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "parallel")
    monkeypatch.setitem(sys.modules, "mcp", None)
    result = search.web_search("current API docs")
    assert result["success"] is False
    assert "uv sync --extra parallel" in result["error"]


def test_parallel_invalid_count_does_not_call_server(parallel_server):
    result = search.web_search("current API docs", num_results=0)
    assert result["success"] is False
    assert not parallel_server.calls


@pytest.mark.parametrize("provider", [None, "exa"])
@pytest.mark.parametrize("include_contents", [True, False])
def test_exa_behavior_preserved(monkeypatch, provider, include_contents):
    if provider is None:
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", provider)
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")
    calls = []

    class FakeExa:
        def __init__(self, *, api_key):
            assert api_key == "test-exa-key"

        def search(self, *args, **kwargs):
            calls.append(("search", args, kwargs))
            return "existing Exa output"

        def search_and_contents(self, *args, **kwargs):
            calls.append(("contents", args, kwargs))
            return "existing Exa output"

    monkeypatch.setattr(search, "Exa", FakeExa)
    result = search.web_search("current API docs", num_results=3, include_contents=include_contents)
    assert result == {"success": True, "results": "existing Exa output", "error": None}
    expected_kwargs = {"num_results": 3, "type": "auto"}
    if include_contents:
        expected_kwargs["text"] = True
    assert calls == [
        ("contents" if include_contents else "search", ("current API docs",), expected_kwargs)
    ]


def test_missing_exa_key_still_disables_search(monkeypatch):
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    assert search.web_search("current API docs") == {
        "success": False,
        "error": "EXA_API_KEY is not configured. Please add it to your environment variables.",
    }


def test_unknown_provider_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "typo")
    result = search.web_search("current API docs")
    assert result["success"] is False
    assert "Unknown WEB_SEARCH_PROVIDER" in result["error"]
