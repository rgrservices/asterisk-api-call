from __future__ import annotations

import asyncio
import logging

import panoramisk

_logger = logging.getLogger("call_api.ami")


class AmiClient:
    """Wrapper sobre panoramisk.Manager que mantém conexão persistente ao AMI."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        secret: str,
        context: str,
        timeout_ms: int,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._secret = secret
        self._context = context
        self._timeout_ms = timeout_ms
        self._manager: panoramisk.Manager | None = None

    @property
    def configured(self) -> bool:
        return bool(self._username and self._secret)

    async def _ensure_connected(self) -> panoramisk.Manager:
        if self._manager is not None:
            return self._manager
        manager = panoramisk.Manager(
            host=self._host,
            port=self._port,
            username=self._username,
            secret=self._secret,
        )
        await manager.connect()
        self._manager = manager
        _logger.info("AMI conectado em %s:%d", self._host, self._port)
        return manager

    async def close(self) -> None:
        if self._manager is not None:
            self._manager.close()
            self._manager = None
            _logger.info("AMI desconectado")

    async def originate(
        self,
        dial_string: str,
        playback_ref: str,
        caller_id: str = "Call API <0000>",
    ) -> dict:
        """
        Origina uma chamada via AMI usando contexto call-api-playback.

        Parâmetros:
            dial_string  : string de discagem (ex.: '200211999999999')
            playback_ref : referência do arquivo de áudio para o Playback()
                           (ex.: 'custom/1/aviso_feriado' — sem extensão)
            caller_id    : CallerID exibido no destino

        Retorna dict com 'status' ('queued'|'failed') e 'uniqueid'.
        Levanta RuntimeError em caso de falha AMI.
        """
        manager = await self._ensure_connected()

        action = {
            "Action": "Originate",
            "Channel": f"Local/{dial_string}@from-internal",
            "Context": self._context,
            "Exten": "s",
            "Priority": "1",
            "CallerID": caller_id,
            "Timeout": str(self._timeout_ms),
            "Variable": f"AUDIO_FILE={playback_ref}",
            "Async": "true",
        }

        try:
            result = await asyncio.wait_for(
                manager.send_action(action),
                timeout=(self._timeout_ms / 1000) + 5,
            )
        except asyncio.TimeoutError as exc:
            self._manager = None
            raise RuntimeError("AMI originate timeout") from exc
        except Exception as exc:
            _logger.error("AMI originate falhou: %s", exc)
            self._manager = None
            raise RuntimeError(f"AMI error: {exc}") from exc

        response = dict(result) if result else {}
        ami_response = response.get("Response", "")

        if ami_response.lower() not in ("success", ""):
            msg = response.get("Message", ami_response)
            raise RuntimeError(f"AMI recusou o originate: {msg}")

        uniqueid = response.get("Uniqueid", "")
        _logger.info(
            "AMI Originate enfileirado: channel=Local/%s@from-internal uniqueid=%s",
            dial_string,
            uniqueid,
        )
        return {"status": "queued", "uniqueid": uniqueid}
