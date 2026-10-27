from __future__ import annotations

import json

import pytest

from app.agent import Agent
from app.config import Settings
from app.llm.base import LLMError, LLMResponse, ToolCall


class ScriptedLLM:
    name = "scripted"
    model = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, tools):
        self.calls.append(messages)
        if not isinstance(self.responses, list):
            return self.responses
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def health(self):
        return {"status": "ok"}


def make_agent(provider, fixture_db, llm, **kwargs):
    settings = Settings(llm_provider="openai", railway_db_path=fixture_db, **kwargs)
    from app.sessions import SessionStore

    sessions = SessionStore()
    return Agent(llm, provider, settings, sessions), sessions


@pytest.mark.asyncio
async def test_agent_executes_tool_then_answers(provider, fixture_db):
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="search_trains",
                        arguments={
                            "from_station": "ALPJ",
                            "to_station": "BETN",
                            "journey_date": "2026-11-15",
                        },
                    )
                ]
            ),
            LLMResponse(content="There are 3 trains, see the table above."),
        ]
    )
    agent, sessions = make_agent(provider, fixture_db, llm)
    session = sessions.get(None)

    response = await agent.chat(session, "Trains from Alpha Jn to Beta Nagar on 2026-11-15")

    assert response.reply.startswith("There are 3 trains")
    assert "no running-day information" in response.reply
    assert response.tool_results[0].ok
    assert len(llm.calls) == 2
    tool_message = llm.calls[1][-1]
    assert tool_message["role"] == "tool"
    assert json.loads(tool_message["content"])["ok"] is True


@pytest.mark.asyncio
async def test_agent_rejects_unknown_tool_and_still_answers(provider, fixture_db):
    llm = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="run_shell", arguments={"cmd": "rm -rf /"})]),
            LLMResponse(content="I could not do that."),
        ]
    )
    agent, sessions = make_agent(provider, fixture_db, llm)
    response = await agent.chat(sessions.get(None), "delete everything")

    assert response.degraded is True
    assert response.tool_results[0].error.code == "unknown_tool"


@pytest.mark.asyncio
async def test_agent_reports_invalid_tool_arguments(provider, fixture_db):
    llm = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="get_train_schedule", arguments={"train_number": "abc"})]),
            LLMResponse(content="That train number is not valid."),
        ]
    )
    agent, sessions = make_agent(provider, fixture_db, llm)
    response = await agent.chat(sessions.get(None), "schedule of abc")
    assert response.tool_results[0].error.code == "invalid_arguments"


@pytest.mark.asyncio
async def test_agent_remembers_last_train(provider, fixture_db):
    llm = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="get_train_schedule", arguments={"train_number": "00002"})]),
            LLMResponse(content="Here is the schedule."),
        ]
    )
    agent, sessions = make_agent(provider, fixture_db, llm)
    session = sessions.get(None)
    await agent.chat(session, "Schedule of 00002")
    assert session.last_train_number == "00002"


@pytest.mark.asyncio
async def test_agent_handles_llm_connection_error(provider, fixture_db):
    llm = ScriptedLLM([LLMError("Could not connect to Ollama.", hint="Run `ollama serve`.")])
    agent, sessions = make_agent(provider, fixture_db, llm)
    response = await agent.chat(sessions.get(None), "hello")
    assert response.degraded is True
    assert "Could not connect" in response.reply
    assert "ollama serve" in response.reply


@pytest.mark.asyncio
async def test_agent_stops_after_max_rounds(provider, fixture_db):
    call = LLMResponse(
        tool_calls=[ToolCall(id="c1", name="get_train_schedule", arguments={"train_number": "00001"})]
    )
    llm = ScriptedLLM([call, call, call, call])
    agent, sessions = make_agent(provider, fixture_db, llm, agent_max_tool_rounds=2)
    response = await agent.chat(sessions.get(None), "loop please")
    assert response.degraded is True
    assert "could not finish" in response.reply.lower()
    assert len(response.tool_results) == 2


@pytest.mark.asyncio
async def test_agent_without_llm_uses_router(provider, fixture_db):
    from app.agent import RuleBasedRouter
    from app.sessions import SessionStore

    settings = Settings(llm_provider="none", railway_db_path=fixture_db)
    sessions = SessionStore()
    router = RuleBasedRouter(provider, sessions)
    agent = Agent(None, provider, settings, sessions, router=router)

    response = await agent.chat(sessions.get(None), "Schedule of train 00001")
    assert response.tool_results[0].ok
    assert "Alpha Jn" in response.reply
