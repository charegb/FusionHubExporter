"""Wording and small checks for the export dialog. No Fusion imports, so they are unit-tested."""

import json
import os
import tempfile

UNWRITABLE = 'Fusion cannot save to this folder. Choose another folder, such as one in your Documents.'
BUSY_NOTE = ('Fusion will be busy until this finishes, which can take a long time. '
             'If Fusion stops, run this again and choose the same folder to continue.')
TOO_LONG = ('The path of this folder is too long. Choose a folder closer to the top of your drive, '
            'such as one in your Documents.')

# Longest folder path accepted; the files and folders under it need the rest of the room
MAX_FOLDER_LEN = 150
NO_DRAWINGS = 'Drawings cannot be exported with this version of Fusion; update Fusion to include them.'
NO_ELECTRONICS = 'Electronics cannot be exported with this version of Fusion; update Fusion to include them.'


def plural(count: int, noun: str) -> str:
    return '{:,} {}{}'.format(count, noun, '' if count == 1 else 's')


def check_writable(folder: str) -> str:
    """Return '' if files can be created in folder (created if needed), else a plain-language message."""
    if not folder or not folder.strip():
        return UNWRITABLE
    if len(folder) > MAX_FOLDER_LEN:
        return TOO_LONG
    try:
        os.makedirs(folder, exist_ok=True)
        handle, path = tempfile.mkstemp(dir=folder, prefix='.hub-export-check-')
        os.close(handle)
        os.remove(path)
    except OSError:
        return UNWRITABLE
    return ''


def resume_line(counts) -> str:
    """The one extra line shown when the chosen folder holds a previous export, or ''."""
    if not counts:
        return ''
    total = sum(count for status, count in counts.items() if status != 'not_exportable')
    if total == 0:
        return ''
    return 'Resume previous export: {} of {} done'.format(counts.get('done', 0), total)


def confirmation_text(hub_name: str, projects: int, files: int, has_drawing: bool, has_electron: bool,
                      notice: str = '') -> str:
    paragraphs = ['Export all of {}: {} in {}.'.format(hub_name, plural(files, 'file'), plural(projects, 'project')),
                  BUSY_NOTE]
    if not has_drawing:
        paragraphs.append(NO_DRAWINGS)
    if not has_electron:
        paragraphs.append(NO_ELECTRONICS)
    if notice:
        paragraphs.append(notice)
    return '\n\n'.join(paragraphs)


def nothing_to_export_text(counts: dict) -> str:
    """What to say when a run has nothing left to do, without calling a partial export complete."""
    done = counts.get('done', 0)
    problems = counts.get('failed', 0) + counts.get('not_exportable', 0)
    if done + problems == 0:
        return 'This hub has no files to export.'
    if done == 0:
        return ('This hub has no files this tool can export. '
                'Your report lists what was skipped and why.')
    if problems:
        return '{} {} exported. {:,} could not be exported or were skipped. Your report lists them.'.format(
            '{:,}'.format(done), 'file is' if done == 1 else 'files are', problems)
    return 'Nothing left to export. All {} {} already exported.'.format(
        done, 'file is' if done == 1 else 'files are')


def load_last_folder(settings_path: str, default: str) -> str:
    """The folder used last time, or default."""
    try:
        with open(settings_path, encoding='utf-8') as f:
            folder = json.load(f).get('output_folder')
        return folder if isinstance(folder, str) and folder else default
    except (OSError, ValueError, AttributeError):
        return default


def save_last_folder(settings_path: str, folder: str):
    try:
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump({'output_folder': folder}, f)
    except OSError:
        pass
