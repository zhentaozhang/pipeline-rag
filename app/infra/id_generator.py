"""
Snowflake ID 生成器

算法：64 bit = 1(符号) + 41(时间戳ms) + 5(数据中心) + 5(机器ID) + 12(序列号)
单机每毫秒最多生成 4096 个唯一 ID，天然有序，适合数据库主键。
"""

import os
import threading
import time


class SnowflakeIDGenerator:
    """
    线程安全的 Snowflake ID 生成器。
    Bit 布局见模块 docstring。
    """

    EPOCH = 1288834974657
    WORKER_ID_BITS = 5
    DATACENTER_ID_BITS = 5
    SEQUENCE_BITS = 12
    MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1
    MAX_DATACENTER_ID = (1 << DATACENTER_ID_BITS) - 1
    MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1
    TIMESTAMP_SHIFT = WORKER_ID_BITS + DATACENTER_ID_BITS + SEQUENCE_BITS
    DATACENTER_ID_SHIFT = WORKER_ID_BITS + SEQUENCE_BITS
    WORKER_ID_SHIFT = SEQUENCE_BITS

    def __init__(self, worker_id: int = 1, datacenter_id: int = 0) -> None:
        if not (0 <= worker_id <= self.MAX_WORKER_ID):
            raise ValueError(f"worker_id must be 0~{self.MAX_WORKER_ID}, got {worker_id}")
        if not (0 <= datacenter_id <= self.MAX_DATACENTER_ID):
            raise ValueError(
                f"datacenter_id must be 0~{self.MAX_DATACENTER_ID}, got {datacenter_id}"
            )
        self.worker_id = worker_id
        self.datacenter_id = datacenter_id
        self._sequence = 0
        self._last_timestamp = -1
        self._lock = threading.Lock()

    def next_id(self) -> int:
        with self._lock:
            ts = self._current_ms()
            if ts < self._last_timestamp:
                raise RuntimeError("Clock moved backwards. Refusing to generate ID.")
            if ts == self._last_timestamp:
                self._sequence = (self._sequence + 1) & self.MAX_SEQUENCE
                if self._sequence == 0:
                    ts = self._wait_next_ms(self._last_timestamp)
            else:
                self._sequence = 0
            self._last_timestamp = ts
            return (
                ((ts - self.EPOCH) << self.TIMESTAMP_SHIFT)
                | (self.datacenter_id << self.DATACENTER_ID_SHIFT)
                | (self.worker_id << self.WORKER_ID_SHIFT)
                | self._sequence
            )

    def _current_ms(self) -> int:
        return int(time.time() * 1000)

    def _wait_next_ms(self, last: int) -> int:
        ts = self._current_ms()
        while ts <= last:
            ts = self._current_ms()
        return ts


_generator_lock = threading.Lock()
_default_generator: SnowflakeIDGenerator | None = None


def get_id_generator() -> SnowflakeIDGenerator:
    global _default_generator
    if _default_generator is None:
        with _generator_lock:
            if _default_generator is None:
                worker_id = int(os.getenv("SNOWFLAKE_WORKER_ID", "0"))
                _default_generator = SnowflakeIDGenerator(worker_id=worker_id, datacenter_id=0)
    return _default_generator


def next_id() -> int:
    return get_id_generator().next_id()


def next_id_int() -> int:
    return next_id()


def next_id_str() -> str:
    return str(next_id())
