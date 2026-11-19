"""Where each exported file goes. No Fusion imports beyond the vendored name helper."""

import hashlib
import os

from ..archiverUtils.file_utils import sanitize_name

# Windows stops working with paths much past 260 characters; stay well under it on every OS
MAX_PATH_LEN = 240

# Shortest a file name or folder name is cut down to
MIN_STEM_LEN = 20
MIN_SEGMENT_LEN = 8

# Room kept for the file name when folder names have to be shortened. Folder names are shortened
# from the folders alone, so every file in a folder ends up in the same shortened folder.
RESERVED_FILE_LEN = 48


class PathTooLongError(Exception):
    """The folders are nested so deeply that no file can be saved under them."""


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:6]


def _shorten(text: str, limit: int) -> str:
    """Cut text to limit characters, ending in a short hash of the original so different names stay different."""
    if len(text) <= limit:
        return text
    return text[:max(limit - 7, 1)] + '-' + _hash(text)


def _clean(name: str) -> str:
    return sanitize_name(name) or 'Untitled'


def hub_folder(root: str, hub: str) -> str:
    """The folder that holds everything exported from a hub: <root>/<hub>. Progress, report and log go here."""
    return os.path.join(root, _clean(hub))


def _fit_folders(root: str, segments: list) -> list:
    """Shorten folder names, if needed, so a file still fits. Depends only on the folders."""
    used = len(root) + sum(len(segment) + 1 for segment in segments)
    if used + RESERVED_FILE_LEN <= MAX_PATH_LEN:
        return segments
    limit = (MAX_PATH_LEN - len(root) - RESERVED_FILE_LEN) // len(segments) - 1
    if limit < MIN_SEGMENT_LEN:
        raise PathTooLongError('The folders are nested too deeply to save this file')
    return [_shorten(segment, limit) for segment in segments]


def plan_output_paths(root: str, hub: str, project: str, folders: list, name: str, extensions: list,
                      claimed: dict) -> list:
    """Return one path per extension: <root>/<hub>/<project>/<folders...>/<name><extension>.

    Every segment is cleaned for Windows and macOS. A name that is empty after cleaning becomes
    Untitled. Over-long paths are shortened (folders first, from the folders alone, then the file
    name) with a short hash on whatever was cut; PathTooLongError if nothing can fit. If the
    lower-cased path of any extension is already in claimed (lower-cased path -> record key),
    " (2)", " (3)" ... is added to the file name for all of them. claimed is not changed; the
    caller records the results.
    """
    segments = _fit_folders(root, [_clean(part) for part in [hub, project] + list(folders)])
    stem = _clean(name)
    folder_path = os.path.join(root, *segments)
    room = MAX_PATH_LEN - len(folder_path) - 1 - max(len(extension) for extension in extensions)
    if room < MIN_STEM_LEN:
        raise PathTooLongError('The folders are nested too deeply to save this file')

    number = 1
    while True:
        suffix = '' if number == 1 else ' ({})'.format(number)
        file_stem = stem + suffix
        if len(file_stem) > room:
            file_stem = _shorten(stem, room - len(suffix)) + suffix
        candidates = [os.path.join(folder_path, file_stem + extension) for extension in extensions]
        if not any(candidate.lower() in claimed for candidate in candidates):
            return candidates
        number += 1


def plan_output_path(root: str, hub: str, project: str, folders: list, name: str, extension: str,
                     claimed: dict) -> str:
    """plan_output_paths for a single extension."""
    return plan_output_paths(root, hub, project, folders, name, [extension], claimed)[0]
