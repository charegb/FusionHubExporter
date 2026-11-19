"""The progress ledger: one JSON file in the output folder that records what happened to every file.

It is what makes an export resumable. It is rewritten atomically after every change, so Fusion
stopping at any moment leaves a readable file. No Fusion imports.
"""

import json
import os
import tempfile
import time

from .model import DONE, FAILED, IN_PROGRESS, MAX_ATTEMPTS, NOT_EXPORTABLE, PENDING, Record

LEDGER_FILE = 'hub-export-progress.json'
SCHEMA_VERSION = 1

CRASH_REASON = 'Fusion stopped while exporting this file'
UPDATED_NOTE = 'updated since the first run'
SET_ASIDE_NOTICE = ('An earlier progress file in this folder could not be used, so it was set aside as {} '
                    'and this export starts fresh.')
REPLACED_NOTICE = ('An earlier progress file in this folder could not be used and could not be moved aside, '
                   'so it will be replaced and this export starts fresh.')

# Another program (cloud sync, antivirus) can briefly hold the file; wait and try again
SAVE_TRIES = 5
SAVE_WAIT_SECONDS = 0.2


class Ledger:
    def __init__(self, folder: str, hub_id: str, hub_name: str):
        self.folder = folder
        self.hub_id = hub_id
        self.hub_name = hub_name
        self.started = time.strftime('%Y-%m-%d %H:%M:%S')
        self.clean_shutdown = True
        self._records = {}  # key -> Record, in the order files were first seen

    # ----------------------------------------------------------------------------------------
    # Loading and saving
    # ----------------------------------------------------------------------------------------

    @property
    def path(self) -> str:
        return os.path.join(self.folder, LEDGER_FILE)

    @classmethod
    def open(cls, folder: str, hub_id: str, hub_name: str):
        """Load the ledger in a folder, or start an empty one. Returns (ledger, notice).

        A ledger that is unreadable, from another schema version or from another hub is renamed
        aside and replaced by an empty one, with a one-line notice. This never raises for bad content.
        """
        ledger = cls(folder, hub_id, hub_name)
        if not os.path.exists(ledger.path):
            return ledger, ''

        try:
            with open(ledger.path, encoding='utf-8') as f:
                data = json.load(f)
            if data['schema_version'] != SCHEMA_VERSION or data['hub_id'] != hub_id:
                raise ValueError('not this hub or schema')
            records = [Record.from_dict(entry) for entry in data['files']]
        except (OSError, ValueError, KeyError, TypeError):
            return ledger, ledger._set_aside()

        ledger.started = data.get('started', ledger.started)
        ledger.clean_shutdown = bool(data.get('clean_shutdown', True))
        for record in records:
            record.output_paths = [ledger._absolute(path) for path in record.output_paths]
        ledger._records = {record.key: record for record in records}
        return ledger, ''

    def _relative(self, path: str) -> str:
        """Stored paths are relative to the ledger's folder, so the folder can be moved or renamed."""
        try:
            relative = os.path.relpath(path, self.folder)
        except ValueError:  # another drive on Windows
            return path
        return path if relative.startswith('..') else relative

    def _absolute(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.normpath(os.path.join(self.folder, path))

    @staticmethod
    def peek_counts(folder: str, hub_id: str):
        """Return the status counts of the ledger in a folder, or None if there is no usable one for this hub.

        Read-only: unlike open, it never renames or changes anything.
        """
        counts = {status: 0 for status in (PENDING, IN_PROGRESS, DONE, FAILED, NOT_EXPORTABLE)}
        try:
            with open(os.path.join(folder, LEDGER_FILE), encoding='utf-8') as f:
                data = json.load(f)
            if data['schema_version'] != SCHEMA_VERSION or data['hub_id'] != hub_id:
                return None
            for entry in data['files']:
                counts[Record.from_dict(entry).status] += 1
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return counts

    def _set_aside(self) -> str:
        new_name = 'hub-export-progress.old-{}.json'.format(time.strftime('%Y%m%d-%H%M%S'))
        try:
            os.replace(self.path, os.path.join(self.folder, new_name))
        except OSError:
            return REPLACED_NOTICE
        return SET_ASIDE_NOTICE.format(new_name)

    def save(self):
        """Write the ledger atomically. Does nothing until there is something to record."""
        if not self._records and not os.path.exists(self.path):
            return
        data = {
            'schema_version': SCHEMA_VERSION,
            'hub_id': self.hub_id,
            'hub_name': self.hub_name,
            'started': self.started,
            'clean_shutdown': self.clean_shutdown,
            'files': [self._to_disk(record) for record in self._records.values()],
        }
        os.makedirs(self.folder, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(dir=self.folder, prefix='.hub-export-progress-', suffix='.tmp')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=1)
                f.flush()
                os.fsync(f.fileno())
            self._replace_with_retry(temp_path)
        except BaseException:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def _to_disk(self, record) -> dict:
        data = record.to_dict()
        data['output_paths'] = [self._relative(path) for path in record.output_paths]
        return data

    def _replace_with_retry(self, temp_path: str):
        for attempt in range(SAVE_TRIES):
            try:
                os.replace(temp_path, self.path)
                return
            except OSError:
                if attempt == SAVE_TRIES - 1:
                    raise
                time.sleep(SAVE_WAIT_SECONDS)

    # ----------------------------------------------------------------------------------------
    # Merging a fresh inventory
    # ----------------------------------------------------------------------------------------

    def merge(self, items: list) -> list:
        """Combine a fresh inventory with what is already recorded. Returns notes about changed files."""
        notes = []
        self._resolve_leftover_in_progress()

        seen = set()
        for item in items:
            if item.key in seen:
                continue
            seen.add(item.key)
            note = self._merge_one(item)
            if note:
                notes.append(note)

        for key in [key for key, record in self._records.items() if key not in seen and record.status != DONE]:
            del self._records[key]

        self.save()
        return notes

    def _resolve_leftover_in_progress(self):
        for record in self._records.values():
            if record.status != IN_PROGRESS:
                continue
            if not self.clean_shutdown and record.attempts >= MAX_ATTEMPTS:
                record.status = FAILED
                record.error = CRASH_REASON
                record.attention = True
                remove_partial_outputs(record)
            else:
                record.status = PENDING

    def _merge_one(self, item) -> str:
        existing = self._records.get(item.key)
        fresh = Record.from_dict(item.to_dict())

        if existing is None:
            self._records[item.key] = fresh
            return ''

        version_changed = existing.version_id != fresh.version_id
        where = '{}/{}'.format(fresh.project, fresh.project_path)

        if existing.status == DONE and fresh.status != NOT_EXPORTABLE:
            if not version_changed and all(os.path.exists(path) for path in existing.output_paths):
                return ''
            fresh.status, fresh.attempts = PENDING, 0
            if version_changed:
                fresh.note = UPDATED_NOTE
                self._records[item.key] = fresh
                return '{}: {}'.format(where, UPDATED_NOTE)
            self._records[item.key] = fresh
            return ''

        if fresh.status == NOT_EXPORTABLE:
            self._records[item.key] = fresh
            return ''

        if existing.status == FAILED and not version_changed and existing.attempts >= MAX_ATTEMPTS:
            fresh.status, fresh.error = FAILED, existing.error
            fresh.attempts, fresh.attention, fresh.note = existing.attempts, existing.attention, existing.note
            self._records[item.key] = fresh
            return ''

        fresh.status = PENDING
        fresh.attempts = 0 if version_changed else existing.attempts
        if version_changed:
            fresh.note = UPDATED_NOTE
        else:
            fresh.note = existing.note
        self._records[item.key] = fresh
        return '{}: {}'.format(where, UPDATED_NOTE) if version_changed else ''

    # ----------------------------------------------------------------------------------------
    # Recording progress
    # ----------------------------------------------------------------------------------------

    def begin_run(self):
        self.clean_shutdown = False
        self.save()

    def end_run(self, clean: bool):
        self.clean_shutdown = clean
        self.save()

    def mark_in_progress(self, key: str):
        record = self._records[key]
        record.status = IN_PROGRESS
        record.attempts += 1
        self.save()

    def mark_done(self, key: str, output_paths: list):
        record = self._records[key]
        record.status = DONE
        record.output_paths = list(output_paths)
        record.error = ''
        record.attention = False
        self.save()

    def mark_failed(self, key: str, reason: str):
        record = self._records[key]
        record.status = FAILED
        record.error = reason
        record.attention = True
        self.save()

    def mark_pending(self, key: str):
        """A clean cancel: the file goes back to waiting and the interrupted try does not count."""
        record = self._records[key]
        record.status = PENDING
        record.attempts = max(record.attempts - 1, 0)
        self.save()

    # ----------------------------------------------------------------------------------------
    # Reading
    # ----------------------------------------------------------------------------------------

    def records(self) -> list:
        return list(self._records.values())

    def get(self, key: str) -> Record:
        return self._records[key]

    def counts(self) -> dict:
        counts = {status: 0 for status in (PENDING, IN_PROGRESS, DONE, FAILED, NOT_EXPORTABLE)}
        for record in self._records.values():
            counts[record.status] += 1
        return counts

    def pending_keys(self) -> list:
        return [key for key, record in self._records.items() if record.status == PENDING]

    def has_work(self) -> bool:
        return bool(self.pending_keys())


def remove_partial_outputs(record):
    """Delete the files a failed export may have left half-written, so they don't look like real exports."""
    for path in record.output_paths:
        try:
            os.remove(path)
        except OSError:
            pass
