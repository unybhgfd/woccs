"""通过学而思的oss (livefile.xesimg.com) 上传文件"""

from typing import Literal, TypedDict, Optional
import os
import hashlib
import urllib.parse
import aiohttp
import rich.progress

__all__ = ["XesFileUploader", "XES_OSS_URL_PREFIX", "file_md5"]

CHUNK_SIZE = 16384  # in bytes
XES_OSS_URL_PREFIX = "https://livefile.xesimg.com/programme/python_assets/"

def file_md5(file_path: str, cli_progress_bar: bool = False):
    """流式计算文件md5"""
    md5 = hashlib.md5()
    if cli_progress_bar:
        progress = rich.progress.Progress()
        task = progress.add_task("processing...", total=os.path.getsize(file_path))
        progress.__enter__()

    with open(file_path, mode="rb") as file:
        while chunk := file.read(CHUNK_SIZE):
            md5.update(chunk)

            if cli_progress_bar:
                progress.update(task, advance=len(chunk)) # type: ignore

    if cli_progress_bar:
        progress.__exit__(None, None, None) # type: ignore
    return md5

class XesFileUploader:
    """将文件上传到oss"""

    _OSSParamDataType = TypedDict("_OSSParamDataType", {
        "host": str,  # 上传时使用的url
        "headers": dict[str, str],  # 上传时使用的请求头
        "url": str,  # 下载时使用的url
    })

    OSSParamType = TypedDict("OSSParamType", {
        "data": _OSSParamDataType
    })

    def __init__(
            self,
            file_path: str,
            filename: str | None = None,
            check_if_exists: Literal["auto", "yes", "no"] = "auto",
    ):
        """init

        Args:
            file: 目标文件的路径
            filename: 上传时使用的文件名称, oss只会使用其后缀
            check_if_exists:
                控制上传前是否查询目标文件是否已存在于oss
                - no: 不执行这个操作
                - yes: 一定执行这个操作
                - auto: 对于大文件 (1MB及以上), 执行这个操作
        """

        if filename is None:
            filename = file_path

        self.file_path = file_path
        self.param: Optional[XesFileUploader.OSSParamType] = None
        self.md5_hex_string = file_md5(file_path).hexdigest()
        self.filename = filename
        self.need_check_upload = False
        self.uploaded = False
        self.file_size = os.path.getsize(self.file_path)

        if check_if_exists == "yes":
            self.need_check_upload = True
        if check_if_exists == "auto" and self.file_size >= 1048576:
            self.need_check_upload = True

    @staticmethod
    async def _static_get_param(md5_hex_string, filename) -> OSSParamType:
        """获取oss param"""

        async with aiohttp.ClientSession() as session:
            response = await session.get(
                "https://code.xueersi.com/api/assets/get_oss_upload_params?"
                + urllib.parse.urlencode({
                    "scene": "offline_python_assets",
                    "md5": md5_hex_string,
                    "filename": "/home/username/" + filename
                }, doseq=True),
                timeout=aiohttp.ClientTimeout(10),
                headers={
                    "Authorization": "e7e380401dc9a31fce2117a60c99ba04"
                }
            )
            response.raise_for_status()
            return await response.json()

    async def _get_param(self) -> OSSParamType:
        if not self.param:
            param = await XesFileUploader._static_get_param(self.md5_hex_string, self.filename)
            self.param = param
            return param
        return self.param

    async def get_oss_url(self) -> str:
        """获取上传后文件对应的url, 即使还没有上传文件"""
        return (await self._get_param())["data"]["url"]

    async def upload(self):
        """上传文件"""

        if self.uploaded:
            return

        async with aiohttp.ClientSession() as session:
            param = (await self._get_param())["data"]

            if self.need_check_upload:
                query_response = await session.get(param["url"])
                query_response.release()

                if query_response.status == 200:
                    self.uploaded = True
                    return

            with open(self.file_path, 'rb') as file:
                upload_response = await session.put(
                    url=param["host"],
                    headers=param["headers"],
                    data=file
                )

            upload_response.raise_for_status()

        self.uploaded = True

    @staticmethod
    async def upload_bytes(data: bytes, filename: str):
        """直接上传bytes对象"""

        md5_hex = hashlib.md5(data).hexdigest()
        param = (await XesFileUploader._static_get_param(md5_hex, filename))["data"]
        async with aiohttp.ClientSession() as session:
            (await session.put(
                url = param["host"],
                headers=param["headers"],
                data=data,
            )).raise_for_status()
        return param["url"]
