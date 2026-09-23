import re

EPISODE_ID_MAX_LENGTH = 100
_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9._-]+$")
_RESERVED_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
} | {f"COM{index}" for index in range(1, 10)} | {
    f"LPT{index}" for index in range(1, 10)
}


class InvalidEpisodeIdError(ValueError):
    """Raised when an episode id cannot be safely used as a filesystem component."""


def validate_episode_id(episode_id: str) -> str:
    if not isinstance(episode_id, str):
        raise InvalidEpisodeIdError(
            f"episode_id must be a string, got {type(episode_id).__name__}"
        )
    if not episode_id:
        raise InvalidEpisodeIdError("episode_id must not be empty")
    if len(episode_id) > EPISODE_ID_MAX_LENGTH:
        raise InvalidEpisodeIdError(
            f"episode_id must be at most {EPISODE_ID_MAX_LENGTH} characters"
        )
    if episode_id in (".", ".."):
        raise InvalidEpisodeIdError("episode_id must not be '.' or '..'")
    if episode_id.startswith("."):
        raise InvalidEpisodeIdError("episode_id must not start with '.'")
    if any(ch in "/\\:" for ch in episode_id):
        raise InvalidEpisodeIdError(
            "episode_id must not contain '/', '\\\\' or ':'"
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in episode_id):
        raise InvalidEpisodeIdError("episode_id must not contain control characters")
    if not _ALLOWED_CHARS.match(episode_id):
        raise InvalidEpisodeIdError(
            "episode_id may only contain ASCII letters, digits, '_', '-' and '.'"
        )
    if episode_id.upper() in _RESERVED_DEVICE_NAMES:
        raise InvalidEpisodeIdError(
            f"episode_id '{episode_id}' is a reserved device name"
        )
    return episode_id
