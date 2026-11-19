"""Plain data types shared by the ledger, inventory, runner and report. No Fusion imports."""

from dataclasses import dataclass, field, fields

# Record statuses
PENDING = 'pending'
IN_PROGRESS = 'in_progress'
DONE = 'done'
FAILED = 'failed'
NOT_EXPORTABLE = 'not_exportable'

# Record kinds
DESIGN = 'design'
DRAWING = 'drawing'
ELECTRONICS = 'electronics'
PROJECT = 'project'
OTHER = 'other'

# A file is tried this many times in total (a crash site is retried once)
MAX_ATTEMPTS = 2


@dataclass
class Record:
    """One file (or project) in the hub and what happened to it."""

    key: str                    # the Fusion data file id (or project id)
    version_id: str
    project: str
    project_path: str           # path inside the project, with folders and the file name
    name: str
    extension: str
    kind: str
    status: str = PENDING
    output_paths: list = field(default_factory=list)
    error: str = ''
    attempts: int = 0
    note: str = ''
    attention: bool = False     # shown under "Needs your attention" in the report

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(Record)}

    @classmethod
    def from_dict(cls, data: dict) -> 'Record':
        known = {f.name for f in fields(Record)}
        return Record(**{key: value for key, value in data.items() if key in known})


@dataclass
class InventoryItem(Record):
    """A Record plus the live Fusion DataFile it came from. The data file is never saved."""

    data_file: object = None
