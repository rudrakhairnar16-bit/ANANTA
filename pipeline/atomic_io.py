import contextlib
import os
import stat
import uuid
from pathlib import Path

_os_replace = os.replace
_os_fsync = os.fsync


def _temp_path(dest: Path) -> Path:
    return dest.parent / f".{dest.name}.{uuid.uuid4().hex}.tmp"


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temp_path(dest)
    created = False
    try:
        with open(tmp, "xb") as handle:
            created = True
            handle.write(data)
            handle.flush()
            _os_fsync(handle.fileno())
        if dest.exists():
            with contextlib.suppress(OSError):
                os.chmod(tmp, stat.S_IMODE(dest.stat().st_mode))
        _os_replace(tmp, dest)
        created = False
    except BaseException:
        if created:
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))
