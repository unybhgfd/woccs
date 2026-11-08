"""消息后端收/发抽象类"""

from abc import ABC, abstractmethod
from typing import Any
import pathlib
from enum import Enum
import json
import time

from upload_file import file_md5

FilesMd5 = dict[str, str]  # {filename: md5}
FilesDiff = dict[str, tuple[str, bool]]  # {filename: (md5, is_deleted)}
StoredDiff = dict[str, tuple[str, float]]  # {filename: (md5, mtime)}
THIS_DIR = pathlib.Path(__file__).resolve().parent / "src"


class MessageTypes(Enum):
    """输出方和接收方的消息类型，是单个字符"""

    SENDER_REPORT_DIFF = "A"
    SENDER_REPORT_FULL = "B"
    RECEIVER_REQUIRE_DIFF = "C"
    RECEIVER_REQUIRE_FULL = "D"


class _AbstractFileSyncBackend(ABC):
    """消息收发后端抽象类"""

    @abstractmethod
    async def refresh(self):
        """轮询刷新，收到消息须调用 self._received"""

    @abstractmethod
    async def send_raw(self, message: str):
        """通过网络发送消息"""

    async def send(self, message: Any, ty: MessageTypes):
        await self.send_raw(ty.value + json.dumps(message))

    async def _received(self, message: str):
        ty = MessageTypes(message[0])
        await self.received(message[1:], ty)

    @abstractmethod
    async def received(self, message: str, ty: MessageTypes):
        """收到消息的回调函数"""

    def _get_full_md5(self) -> FilesMd5:
        """获取目录下所有目标文件与其哈希"""

        paths = THIS_DIR.iterdir()
        diffs: FilesMd5 = {}
        for i in paths:
            if i.is_file() and i.suffix == ".wgsl":
                diffs[str(i)] = file_md5(str(i)).hexdigest()
        return diffs


class AbstractFileSyncBackendSender(_AbstractFileSyncBackend):
    """文件同步输出方"""

    def __init__(self) -> None:
        self.prev_check_time = time.time()
        # TODO

    async def sync_diff(self):
        """推送差异"""

    async def sync_full(self):
        """推送全量"""

        message = self._get_full_md5()
        await self.send(message, MessageTypes.SENDER_REPORT_FULL)

    async def received(self, message: str, ty: MessageTypes):
        if ty == MessageTypes.RECEIVER_REQUIRE_DIFF:
            await self.sync_diff()
        elif ty == MessageTypes.RECEIVER_REQUIRE_FULL:
            await self.sync_full()


class AbstractFileSyncBackendReceiver(_AbstractFileSyncBackend):
    """文件同步接收方"""
