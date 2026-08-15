"""文档数据源连接器抽象（P3-3）

统一模式：列出文件 → 下载到本地 → 触发文档处理流水线。
首个实现为 S3 连接器（与 MinIO 同构，S3 协议兼容），后续可扩展 Confluence/网页爬虫。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConnectorFile:
    """连接器发现的一个待导入文件"""

    remote_key: str  # 远程对象键（S3 key / URL / 页面 id）
    name: str  # 文件名（含扩展名，用于类型判断）
    size: int = 0


class DocumentConnector(ABC):
    """文档连接器基类"""

    @abstractmethod
    async def list_files(self) -> list[ConnectorFile]:
        """列出数据源中可导入的文件"""

    @abstractmethod
    async def fetch_to_local(self, file: ConnectorFile, dest_dir: Path) -> Path:
        """下载文件到本地临时目录，返回本地路径"""

    def supports(self, name: str, file_types: list[str]) -> bool:
        """判断文件扩展名是否在允许清单内"""
        if not file_types:
            return True
        suffix = Path(name).suffix.lower()
        return suffix in file_types
