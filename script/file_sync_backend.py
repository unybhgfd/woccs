"""消息后端收/发抽象类"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine
import pathlib
from enum import Enum
import json
import time
import asyncio
import aiohttp

import rich.progress
from rich import print

from upload_file import XesFileUploader, XES_OSS_URL_PREFIX

__all__ = [
    "FILE_RGLOB_PATTERN",
    "AbstractFileSyncApi",
]

FilesFull = dict[str, str]  # {filepath: md5}
FilesDiff = dict[
    str, str | int
]  # {filepath: md5 | 0}，若文件是新文件/已修改则值是 md5，否则为 0
FILE_RGLOB_PATTERN = "*.wgsl"


class MessageTypes(Enum):
    """输出方和接收方的消息类型，是单个字符"""

    SENDER_REPORT_DIFF = "A"  # 推送差异，有可能是全量，进行上传
    SENDER_REPORT_FULL = "B"  # 推送全量，不进行上传
    RECEIVER_REQUIRE_DIFF = "C"  # 无消息内容
    RECEIVER_REQUIRE_FULL = "D"  # 无消息内容


class Msgs:
    SEND = "[cyan]SEND"
    RECV = "[cyan]RECV"
    ERROR = "[bold red]ERR "
    SYNC = "[magenta]SYNC"


async def async_no_op(_: str) -> None:
    """空异步函数"""


class AbstractFileSyncApi(ABC):
    """文件同步网络后端抽象类"""

    def __init__(self) -> None:
        self._handle: Callable[[str], Coroutine[Any, Any, Any]] = async_no_op

    @abstractmethod
    async def _refresh(self):
        """轮询刷新，新消息调用 `self._handle`"""

    @abstractmethod
    async def _send_raw(self, message: str):
        """通过网络发送消息"""

    def sender(self):
        obj = FileSyncSender(self)
        self._handle = obj._received_raw
        return obj

    def receiver(self):
        obj = FileSyncReceiver(self)
        self._handle = obj._received_raw
        return obj


class _FileSync(ABC):
    def __init__(self, api: AbstractFileSyncApi):
        self.api = api

    async def refresh(self):
        """轮询刷新"""
        await self.api._refresh()

    async def _send_raw(self, message: str):
        await self.api._send_raw(message)

    async def _send(self, message: Any, ty: MessageTypes):
        print(Msgs.SEND, ty.name)
        await self._send_raw(ty.value + json.dumps(message))

    async def _received_raw(self, message: str):
        ty = MessageTypes(message[0])
        print(Msgs.RECV, ty.name)
        await self._received(message[1:], ty)

    @abstractmethod
    async def _received(self, message: str, ty: MessageTypes):
        """收到消息的回调函数"""


class FileSyncSender(_FileSync):
    """文件同步输出方，只读并上传文件。假设文件数量少且体积不大"""

    TARGET_DIR = pathlib.Path(__file__).resolve().parent / "src"

    def __init__(self, api: AbstractFileSyncApi) -> None:
        super().__init__(api)
        self._prev_check_time = 0
        self._paths_set: set[str] = set()

    async def _upload_full_md5(self) -> FilesFull:
        """范围：上限为 `self.prev_check_time`"""
        paths = self.TARGET_DIR.rglob(FILE_RGLOB_PATTERN)
        diffs: FilesFull = {}
        self._paths_set = set()
        for path_abs in paths:
            if path_abs.is_file() and path_abs.stat().st_mtime < self._prev_check_time:
                path_rel = path_abs.relative_to(self.TARGET_DIR)

                self._paths_set.add(str(path_rel))
                uploader = XesFileUploader(str(path_abs), str(path_abs))
                await uploader.upload()
                diffs[str(path_rel)] = uploader.md5_hex_string

        return diffs

    def _get_diff_files(self, max_time: float) -> set[str]:
        """范围：`self._prev_check_time` 到 `max_time`"""
        paths = self.TARGET_DIR.rglob(FILE_RGLOB_PATTERN)
        diffs: set[str] = set()
        self._paths_set = set()
        for path_abs in paths:
            if path_abs.is_file():
                path_rel = path_abs.relative_to(self.TARGET_DIR)

                self._paths_set.add(str(path_rel))
                if self._prev_check_time <= path_abs.stat().st_mtime < max_time:
                    diffs.add(str(path_abs))
        return diffs

    async def _sync_diff(self):
        print(Msgs.SYNC, "请求[black]增量[/]同步")
        if self._prev_check_time == 0:
            await self._sync_full()
            return

        now = time.time()
        prev_paths = self._paths_set.copy()
        changed = self._get_diff_files(now)
        added = self._paths_set - prev_paths  # 新增和修改
        deleted = prev_paths - self._paths_set

        result: FilesDiff = {i: 0 for i in deleted}
        for i in rich.progress.track(added | changed):
            uploader = XesFileUploader(str(self.TARGET_DIR / i), i)
            await uploader.upload()
            result[i] = uploader.md5_hex_string

        await self._send(result, MessageTypes.SENDER_REPORT_DIFF)

    async def _sync_full(self):
        print(Msgs.SYNC, "请求[bold black]全量[/]同步")
        self._prev_check_time = time.time()
        message = await self._upload_full_md5()
        await self._send(message, MessageTypes.SENDER_REPORT_FULL)

    async def _received(self, message: str, ty: MessageTypes):
        if ty == MessageTypes.RECEIVER_REQUIRE_DIFF:
            await self._sync_diff()
        elif ty == MessageTypes.RECEIVER_REQUIRE_FULL:
            await self._sync_full()
        else:
            print(Msgs.ERROR, "错误的消息：", {"ty": ty, "message": message})


class FileSyncReceiver(_FileSync):
    """文件同步接收方，更新自身文件"""

    TARGET_DIR = pathlib.Path(__file__).resolve().parent / "src"

    def __init__(self, api: AbstractFileSyncApi) -> None:
        super().__init__(api)
        self.received_event = asyncio.Event()
        self.need_full = True

    async def _write(self, uploaded_md5: str, path: pathlib.Path):
        async with aiohttp.ClientSession() as session:
            # 不加最后的点号会 404
            response = await session.get(XES_OSS_URL_PREFIX + uploaded_md5 + ".")
            if response.status != 200:
                print(Msgs.ERROR, "无法下载文件", uploaded_md5)
            if path.exists():
                print(Msgs.SYNC, "[yellow]修改[/]文件", str(path))
            else:
                print(Msgs.SYNC, "[greed]新增[/]文件", str(path))

            path.write_text(await response.text())

    async def _received(self, message: str, ty: MessageTypes):
        if ty == MessageTypes.SENDER_REPORT_DIFF:
            print(Msgs.SYNC, "开始[black]增量[/]同步...")
            data_d: FilesDiff = json.loads(message)
            for path_str in data_d:
                path_abs = self.TARGET_DIR / path_str
                v = data_d[path_str]
                if isinstance(v, str):
                    await self._write(v, path_abs)
                else:
                    print(Msgs.SYNC, "[red]删除[/]文件", str(path_abs))
                    path_abs.unlink()
        elif ty == MessageTypes.SENDER_REPORT_FULL:
            print(Msgs.SYNC, "开始[bold black]全量[/]同步...")
            print("     不删除旧文件")
            data_f: FilesFull = json.loads(message)
            for path_str in data_f:
                path_abs = self.TARGET_DIR / path_str
                await self._write(data_f[path_str], path_abs)
        else:
            print(Msgs.ERROR, "错误的消息：", {"ty": ty, "message": message})
            return
        self.received_event.set()

    async def send_and_wait(self, timeout=2.0):
        """等待直到同步完成或超时

        Args:
            timeout: 超时时间（秒）
        """

        self.received_event.clear()
        if self.need_full:
            await self._send("", MessageTypes.RECEIVER_REQUIRE_FULL)
        else:
            await self._send("", MessageTypes.RECEIVER_REQUIRE_DIFF)
        await asyncio.wait_for(self.received_event.wait(), timeout)
