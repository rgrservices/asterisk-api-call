"""Testes do cliente AMI."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from panoramisk.message import Message

from app.ami import AmiClient, _extract_ami_message


class TestExtractAmiMessage:
    def test_empty_result(self):
        assert _extract_ami_message(None) == {}
        assert _extract_ami_message([]) == {}

    def test_single_message(self):
        msg = Message({"Response": "Success", "Uniqueid": "abc123"})
        assert _extract_ami_message(msg) is msg

    def test_async_originate_list_picks_success(self):
        queued = Message(
            {
                "Response": "Success",
                "Message": "Originate successfully queued",
                "ActionID": "action/test/1/1",
            }
        )
        follow_up = Message({"Event": "OriginateResponse", "Response": "Failure"})
        assert _extract_ami_message([queued, follow_up]) is queued

    def test_async_originate_list_fallback_to_first(self):
        first = Message({"Event": "FullyBooted"})
        assert _extract_ami_message([first]) is first


class TestAmiClientOriginate:
    @pytest.mark.asyncio
    async def test_originate_handles_async_response_list(self):
        client = AmiClient("127.0.0.1", 5038, "u", "s", "ctx", 30000)
        manager = MagicMock()
        manager.send_action = AsyncMock(
            return_value=[
                Message(
                    {
                        "Response": "Success",
                        "Message": "Originate successfully queued",
                        "Uniqueid": "1700000000.1",
                    }
                )
            ]
        )

        with patch.object(client, "_ensure_connected", AsyncMock(return_value=manager)):
            result = await client.originate("200211999999999", "custom/1/teste")

        assert result == {"status": "queued", "uniqueid": "1700000000.1"}
