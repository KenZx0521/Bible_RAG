"""query_rag's request body: the per-request overrides go out only when the caller sets them."""

import asyncio

import pytest

from src.rag_client import query_rag


class _Resp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"answer": "", "sources": []}


class _Client:
    def __init__(self):
        self.bodies = []

    async def post(self, url, json):
        self.bodies.append(json)
        return _Resp()


def _body(**kw) -> dict:
    client = _Client()
    asyncio.run(query_rag("q", client=client, **kw))
    return client.bodies[0]


def test_no_card_flag_is_sent_by_default():
    body = _body()
    assert "use_gen_card" not in body and "use_regnal_card" not in body


@pytest.mark.parametrize("value", [True, False])
def test_the_gen_card_flag_is_sent_when_set(value):
    body = _body(use_gen_card=value)
    assert body["use_gen_card"] is value and "use_regnal_card" not in body


def test_both_card_flags_go_out_independently():
    body = _body(use_regnal_card=True, use_gen_card=False)
    assert (body["use_regnal_card"], body["use_gen_card"]) == (True, False)
