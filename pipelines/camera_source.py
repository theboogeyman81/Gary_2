"""
Camera source abstraction for the gesture pipeline.

Pipelines depend on CameraSource, not concrete implementations.
The source is chosen at runtime via make_camera_source(spec) where
spec is a string like "mac:0" or "xiao:192.168.1.10".
"""

import asyncio
from typing import AsyncIterator, Protocol, runtime_checkable

import cv2
import numpy as np


@runtime_checkable
class CameraSource(Protocol):
    async def frames(self) -> AsyncIterator[np.ndarray]: ...
    async def close(self) -> None: ...


class MacWebcam:
    """
    USB webcam via OpenCV, non-blocking via asyncio.to_thread.

    device_index: the integer index passed to cv2.VideoCapture.
    Run scripts/list_cameras.py to discover which index is which camera.
    """

    def __init__(self, device_index: int) -> None:
        self._index = device_index
        self._cap: cv2.VideoCapture | None = None

    def _open(self) -> None:
        cap = cv2.VideoCapture(self._index)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera index {self._index}")
        self._cap = cap

    def _read_frame(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        return frame if ok else None

    async def frames(self) -> AsyncIterator[np.ndarray]:
        if self._cap is None:
            await asyncio.to_thread(self._open)
        while True:
            frame = await asyncio.to_thread(self._read_frame)
            if frame is None:
                raise RuntimeError(f"Camera {self._index} stopped producing frames")
            yield frame

    async def close(self) -> None:
        if self._cap is not None:
            await asyncio.to_thread(self._cap.release)
            self._cap = None


class XiaoStream:
    """
    Placeholder for XIAO ESP32-S3 MJPEG/WebRTC stream.
    Implement when XIAO firmware is ready. Same CameraSource interface.
    """

    def __init__(self, host: str) -> None:
        self._host = host

    async def frames(self) -> AsyncIterator[np.ndarray]:  # type: ignore[override]
        raise NotImplementedError(f"XiaoStream ({self._host}) not yet implemented")
        yield  # makes this an async generator so the return type is valid

    async def close(self) -> None:
        pass


def make_camera_source(spec: str) -> CameraSource:
    """
    Parse a camera spec string and return the right CameraSource.

    Formats:
      "mac:N"       → MacWebcam(N)
      "xiao:HOST"   → XiaoStream(HOST)
    """
    if spec.startswith("mac:"):
        index = int(spec.split(":", 1)[1])
        return MacWebcam(index)
    if spec.startswith("xiao:"):
        host = spec.split(":", 1)[1]
        return XiaoStream(host)
    raise ValueError(f"Unknown camera spec: {spec!r}. Expected 'mac:N' or 'xiao:HOST'")
