"""Lists every file in a hub, without opening any of them, and plans where each one will be saved."""

# Feature-detect the Electronics and Drawing APIs. Older Fusion versions don't have them, and
# importing them unconditionally would stop the add-in from loading at all on those versions.
try:
    import adsk.electron  # noqa: F401
    HAS_ELECTRON = True
except ImportError:
    HAS_ELECTRON = False

try:
    import adsk.drawing  # noqa: F401
    HAS_DRAWING = True
except ImportError:
    HAS_DRAWING = False

from ..archiverUtils.export_options import DESIGN_FILE_EXTENSION, DRAWING_FILE_EXTENSION, ELECTRONICS_EXPORTS
from .model import (DESIGN, DRAWING, ELECTRONICS, NOT_EXPORTABLE, OTHER, PENDING, PROJECT, InventoryItem)
from .paths import PathTooLongError, plan_output_paths

DESIGN_OUTPUT_EXTENSION = '.step'
DRAWING_OUTPUT_EXTENSIONS = ['.pdf', '.dwg']
CONTAINER_EXTENSION = 'fprj'

NO_DRAWING_API = 'Drawings cannot be exported with this version of Fusion'
NO_ELECTRONICS_API = 'Electronics cannot be exported with this version of Fusion'
CONTAINER_REASON = 'Electronics design container; its schematic and board are exported separately'
NOT_A_FUSION_FILE = 'Not a Fusion file, so it was not exported. Download it from Fusion directly'
UNREADABLE_PROJECT = 'Fusion would not let this tool read this project'
UNREADABLE_FOLDER = 'Fusion would not let this tool read this folder'
TOO_DEEP = ('The folders are nested so deeply that the path is too long to save on this computer. '
            'Move the file closer to the top of its project and export again')


def collect_inventory(hub, output_root: str, claimed: dict, known_paths: dict) -> list:
    """Return an InventoryItem for every file in every project of a hub.

    claimed (lower-cased path -> key) is filled in as paths are planned. known_paths maps a key to
    the output paths already stored in the ledger; those are reused and reserved first, so a
    resumed run saves each file where the first run did.
    """
    for key, paths in known_paths.items():
        for path in paths:
            claimed[path.lower()] = key

    items = []
    seen = {}
    for project in sorted(hub.dataProjects, key=_safe_name):
        try:
            project_items = _walk_project(hub, project, output_root, claimed, known_paths, seen)
        except RuntimeError:
            items.append(InventoryItem(key=project.id, version_id='', project=project.name, project_path='',
                                       name=project.name, extension='', kind=PROJECT, status=NOT_EXPORTABLE,
                                       error=UNREADABLE_PROJECT, attention=True))
            continue
        items.extend(project_items)
    return items


def _safe_name(entity) -> str:
    try:
        return entity.name.lower()
    except RuntimeError:
        return ''


def _read_folder(folder):
    """Return (files, subfolders) of a folder, trying twice since Fusion's cloud data can hiccup."""
    for attempt in (1, 2):
        try:
            return list(folder.dataFiles), list(folder.dataFolders)
        except RuntimeError:
            if attempt == 2:
                raise


def _walk_project(hub, project, output_root, claimed, known_paths, seen) -> list:
    items = []

    def walk(folder, folder_names):
        try:
            files, subfolders = _read_folder(folder)
        except RuntimeError:
            where = '/'.join(folder_names)
            items.append(InventoryItem(key='{}:{}'.format(project.id, where), version_id='', project=project.name,
                                       project_path=where, name=folder_names[-1] if folder_names else project.name,
                                       extension='', kind=PROJECT, status=NOT_EXPORTABLE, error=UNREADABLE_FOLDER,
                                       attention=True))
            return

        for data_file in sorted(files, key=lambda f: (f.name.lower(), f.id)):
            where = '/'.join(folder_names + [data_file.name])
            if data_file.id in seen:
                first = seen[data_file.id]
                first.note = ('{} also appears at {}/{}'.format(first.note, project.name, where)).strip()
                continue
            item = _make_item(hub, project, folder_names, data_file, output_root, claimed, known_paths)
            seen[data_file.id] = item
            items.append(item)
        for sub in sorted(subfolders, key=_safe_name):
            walk(sub, folder_names + [sub.name])

    walk(project.rootFolder, [])
    return items


def _make_item(hub, project, folder_names, data_file, output_root, claimed, known_paths) -> InventoryItem:
    extension = data_file.fileExtension
    item = InventoryItem(key=data_file.id, version_id=data_file.versionId, project=project.name,
                         project_path='/'.join(folder_names + [data_file.name]), name=data_file.name,
                         extension=extension, kind=OTHER, data_file=data_file)

    output_extensions = None
    if extension == DESIGN_FILE_EXTENSION:
        item.kind, output_extensions = DESIGN, [DESIGN_OUTPUT_EXTENSION]

    elif extension == DRAWING_FILE_EXTENSION:
        item.kind = DRAWING
        if HAS_DRAWING:
            output_extensions = DRAWING_OUTPUT_EXTENSIONS
        else:
            _not_exportable(item, NO_DRAWING_API, True)

    elif extension in ELECTRONICS_EXPORTS:
        item.kind = ELECTRONICS
        if HAS_ELECTRON:
            output_extensions = [ELECTRONICS_EXPORTS[extension][1]]
        else:
            _not_exportable(item, NO_ELECTRONICS_API, True)

    elif extension == CONTAINER_EXTENSION:
        item.kind = ELECTRONICS
        _not_exportable(item, CONTAINER_REASON, False)

    else:
        _not_exportable(item, NOT_A_FUSION_FILE, True)

    if output_extensions:
        stored = known_paths.get(item.key)
        if stored and len(stored) == len(output_extensions):
            item.output_paths = list(stored)
            item.status = PENDING
        else:
            try:
                paths = plan_output_paths(output_root, hub.name, project.name, folder_names, data_file.name,
                                          output_extensions, claimed)
            except PathTooLongError:
                _not_exportable(item, TOO_DEEP, True)
            else:
                for path in paths:
                    claimed[path.lower()] = item.key
                item.output_paths = paths
                item.status = PENDING

    return item


def _not_exportable(item, reason: str, attention: bool):
    item.status = NOT_EXPORTABLE
    item.error = reason
    item.attention = attention
