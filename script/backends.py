import json
import math
import time
from typing import Any, Coroutine

from websockets.asyncio.client import connect

from file_sync_backend import AbstractFileSyncApi


def divmod_fi(a: float, b: int):
    return math.floor(a) // b, a % b


class XesCloudVarBackend(AbstractFileSyncApi):
    VarData = tuple[float, str]  # (time, message)

    async def _get_socks(self, t=time.time()):
        group, bias = divmod_fi(t, self.group_time)
        socket = await connect(
            "wss://api.xueersi.com/codecloudvariable/ws:80"
        ).__aenter__()
        socket_prev = None
        if bias < self.check_prev_time:
            socket_prev = await connect(
                "wss://api.xueersi.com/codecloudvariable/ws:80"
            ).__aenter__()
        return (socket_prev, socket)

    async def _pre_refresh(self, t=time.time()):
        group, bias = divmod_fi(t, self.group_time)
        socket = await connect(
            "wss://api.xueersi.com/codecloudvariable/ws:80"
        ).__aenter__()
        await socket.send(
            json.dumps(
                {
                    "method": "handshake",
                    "user": self.uid,
                    "project_id": self.pid_prefix + str(group),
                }
            )
        )
        socket_prev = None
        if bias < self.check_prev_time:
            socket_prev = await connect(
                "wss://api.xueersi.com/codecloudvariable/ws:80"
            ).__aenter__()
            await socket_prev.send(
                json.dumps(
                    {
                        "method": "handshake",
                        "user": self.uid,
                        "project_id": self.pid_prefix + str(group),
                    }
                )
            )
        return (socket_prev, socket)

    def __init__(
        self, pid_prefix, check_prev_time=1.5, group_time: int = 5, uid="1"
    ) -> None:
        super().__init__()
        self.check_prev_time = check_prev_time
        self.group_time = group_time
        self.uid = uid
        self.pid_prefix = pid_prefix
        self.time_last = time.time()
        self.data = self._pre_refresh(self.time_last)

    async def _refresh(self):
        data = await self.data
        messages: set[str] = set()
        results: list[Coroutine[Any, Any, Any]] = []
        now = time.time()
        for client in data:
            if client is None:
                continue
            async for i in client.recv_messages.get_iter(True):
                messages.add(i)

        for s in messages:
            try:
                data: XesCloudVarBackend.VarData | Any = json.loads(s)
                t = data[0]
                msg = data[1]
                if (
                    isinstance(t, float)
                    and isinstance(msg, str)
                    and self.time_last <= t < now
                ):
                    results.append(self._handle(msg))
            except Exception:
                print("消息格式错误：", s)

        self.time_last = now
        self.data = self._pre_refresh(self.time_last)

        for i in results:
            await i

    async def _send_raw(self, message: str):
        clients = await self._get_socks()
        for c in clients:
            if c is None:
                continue
            c.send(json.)  # TODO
