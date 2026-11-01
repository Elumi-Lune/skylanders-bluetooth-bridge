"""Serialise uniquement les SCANS Windows de plusieurs périphériques BLE."""
import asyncio
import threading

_SCAN_LOCK = threading.Lock()

async def guarded_discover(scanner, **kwargs):
    while not _SCAN_LOCK.acquire(blocking=False):
        await asyncio.sleep(.15)
    try:
        return await scanner.discover(**kwargs)
    finally:
        _SCAN_LOCK.release()
