"""
Camera source abstraction for the gesture pipeline.

Pipelines depend on CameraSource, not concrete implementations.
The source is chosen at runtime via make_camera_source(spec) where
spec is a string like "mac:0" or "xiao:192.168.1.10".
"""

import asyncio
import time
from typing import AsyncIterator, Protocol, runtime_checkable

import cv2
import numpy as np


@runtime_checkable
class CameraSource(Protocol):
    async def open(self) -> None: ...
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
        # CAP_AVFOUNDATION is the correct macOS backend for USB webcams.
        cap = cv2.VideoCapture(self._index, cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera index {self._index}")
        # Keep only the most recent frame in the buffer so slow consumers (YOLO)
        # don't cause the buffer to fill and stall the AVFoundation session.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # Fast fixed-count flush.
        for _ in range(60):
            cap.read()
        self._cap = cap

    def _read_frame(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        return frame if ok else None

    async def open(self) -> None:
        if self._cap is None:
            await asyncio.to_thread(self._open)

    async def frames(self) -> AsyncIterator[np.ndarray]:
        await self.open()
        consecutive_failures = 0
        while True:
            frame = await asyncio.to_thread(self._read_frame)
            if frame is None:
                consecutive_failures += 1
                if consecutive_failures >= 60:
                    raise RuntimeError(f"Camera {self._index} stopped producing frames")
                await asyncio.sleep(0.05)
                continue
            consecutive_failures = 0
            yield frame

    async def close(self) -> None:
        if self._cap is not None:
            await asyncio.to_thread(self._cap.release)
            self._cap = None


class XiaoStream:
    """
    MJPEG stream from a XIAO ESP32-S3 Sense running gary_camera firmware.

    Reads the multipart/x-mixed-replace HTTP stream on a background thread
    (requests is blocking), decodes JPEG frames by scanning for SOI/EOI markers,
    and bridges to the async generator via an asyncio.Queue.
    """

    def __init__(self, host: str) -> None:
        self._host = host
        self._url = f"http://{host}/stream"
        self._stop = asyncio.Event()

    async def open(self) -> None:
        pass

    async def frames(self) -> AsyncIterator[np.ndarray]:
        import threading
        import requests

        self._stop.clear()
        queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue(maxsize=2)
        loop = asyncio.get_running_loop()

        def _reader() -> None:
            try:
                resp = requests.get(self._url, stream=True, timeout=(10, None))
                buf = b""
                for chunk in resp.iter_content(chunk_size=4096):
                    if self._stop.is_set():
                        break
                    buf += chunk
                    while True:
                        start = buf.find(b'\xff\xd8')
                        end = buf.find(b'\xff\xd9', start + 2 if start != -1 else 0)
                        if start == -1 or end == -1:
                            break
                        jpg = buf[start:end + 2]
                        buf = buf[end + 2:]
                        frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            asyncio.run_coroutine_threadsafe(queue.put(frame), loop).result(timeout=5)
            except Exception as exc:
                print(f"[XiaoStream] reader error: {exc}")
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        try:
            while True:
                frame = await queue.get()
                if frame is None:
                    raise RuntimeError(f"XiaoStream ({self._host}) stream ended or failed")
                yield frame
        finally:
            self._stop.set()

    async def close(self) -> None:
        self._stop.set()


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
