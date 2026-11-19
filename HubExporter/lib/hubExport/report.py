"""The end-of-run report, as one printable HTML page and a CSV copy. No Fusion imports."""

import csv
import html
import io
import os
import time
from collections import OrderedDict

from .model import DESIGN, DONE, DRAWING, ELECTRONICS, FAILED, IN_PROGRESS, NOT_EXPORTABLE, OTHER, PENDING, PROJECT

REPORT_HTML = 'Hub export report.html'
REPORT_CSV = 'Hub export report.csv'

BANNER = 'This export was stopped before it finished. Run it again to continue.'

TYPE_LABELS = {
    DESIGN: 'Design (STEP)',
    DRAWING: 'Drawing (PDF and DWG)',
    ELECTRONICS: 'Electronics (EAGLE)',
    PROJECT: 'Project',
    OTHER: 'Other file',
}
STATUS_LABELS = {
    DONE: 'Exported',
    FAILED: 'Failed',
    NOT_EXPORTABLE: 'Not exported',
    PENDING: 'Not done yet',
    IN_PROGRESS: 'Not done yet',
}

CSS = """
body { font-family: -apple-system, 'Segoe UI', Arial, sans-serif; margin: 2em auto; max-width: 60em; color: #222; }
h1 { font-size: 1.6em; } h2 { font-size: 1.2em; margin-top: 1.8em; border-bottom: 1px solid #ccc; }
table { border-collapse: collapse; width: 100%; font-size: 0.9em; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #eee; vertical-align: top; }
.banner { background: #fff4ce; border: 1px solid #e0c060; padding: 0.6em 1em; margin: 1em 0; }
.attention { background: #fdecea; border: 1px solid #e0a0a0; padding: 0.2em 1em 0.8em; margin: 1.5em 0; }
.attention h2 { border: 0; margin-top: 0.6em; }
.muted { color: #666; }
@media print { body { margin: 0; } }
"""


def _fusion_path(record) -> str:
    return '{}/{}'.format(record.project, record.project_path) if record.project_path else record.project


def _saved_as(record) -> str:
    """Where a file was saved. Only exported files have a saved copy; planned paths mean nothing otherwise."""
    return '; '.join(record.output_paths) if record.status == DONE else ''


def _reason(record) -> str:
    return ' '.join(part for part in (record.error, record.note) if part)


def _unfinished(records) -> bool:
    return any(record.status in (PENDING, IN_PROGRESS) for record in records)


def build_report(records: list, hub_name: str, cancelled: bool, notices: list):
    """Return (html, csv_text) for a list of ledger records."""
    esc = html.escape
    parts = ['<!DOCTYPE html><html><head><meta charset="utf-8"><title>Hub export report</title>',
             '<style>{}</style></head><body>'.format(CSS),
             '<h1>Hub export report: {}</h1>'.format(esc(hub_name)),
             '<p class="muted">{}</p>'.format(esc(time.strftime('%Y-%m-%d %H:%M')))]

    if cancelled or _unfinished(records):
        parts.append('<div class="banner">{}</div>'.format(esc(BANNER)))

    for notice in notices:
        parts.append('<p>{}</p>'.format(esc(notice)))

    if not records:
        parts.append('<p>Nothing to export. This hub has no files.</p>')

    else:
        exported = {kind: 0 for kind in (DESIGN, DRAWING, ELECTRONICS)}
        for record in records:
            if record.status == DONE and record.kind in exported:
                exported[record.kind] += 1
        failed = sum(record.status == FAILED for record in records)
        not_exportable = sum(record.status == NOT_EXPORTABLE for record in records)
        remaining = sum(record.status in (PENDING, IN_PROGRESS) for record in records)
        parts.append('<h2>Summary</h2><ul>')
        for kind, count in exported.items():
            parts.append('<li>{}: {} exported</li>'.format(esc(TYPE_LABELS[kind]), count))
        parts.append('<li>Failed: {}</li><li>Not exported: {}</li><li>Not done yet: {}</li></ul>'.format(
            failed, not_exportable, remaining))

        attention = [record for record in records if record.attention]
        if attention:
            parts.append('<div class="attention"><h2>Needs your attention</h2><table>'
                         '<tr><th>Where it is in Fusion</th><th>What happened</th></tr>')
            for record in attention:
                parts.append('<tr><td>{}</td><td>{}</td></tr>'.format(esc(_fusion_path(record)),
                                                                      esc(_reason(record))))
            parts.append('</table></div>')

        by_project = OrderedDict()
        for record in records:
            by_project.setdefault(record.project, []).append(record)
        for project, project_records in by_project.items():
            parts.append('<h2>{}</h2><table><tr><th>Path in Fusion</th><th>Type</th><th>Status</th>'
                         '<th>Saved as</th><th>Note</th></tr>'.format(esc(project)))
            for record in project_records:
                parts.append('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                    esc(record.project_path or record.name), esc(TYPE_LABELS.get(record.kind, record.kind)),
                    esc(STATUS_LABELS.get(record.status, record.status)),
                    esc(_saved_as(record)), esc(_reason(record))))
            parts.append('</table>')

    parts.append('</body></html>')

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(['project', 'path in Fusion', 'type', 'status', 'output file', 'note or reason'])
    for record in records:
        writer.writerow([record.project, _fusion_path(record), TYPE_LABELS.get(record.kind, record.kind),
                         STATUS_LABELS.get(record.status, record.status), _saved_as(record),
                         _reason(record)])

    return ''.join(parts), buffer.getvalue()


def write_report(folder: str, records: list, hub_name: str, cancelled: bool, notices: list) -> str:
    """Write the HTML and CSV report into folder and return the HTML path."""
    html_text, csv_text = build_report(records, hub_name, cancelled, notices)
    os.makedirs(folder, exist_ok=True)
    html_path = os.path.join(folder, REPORT_HTML)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_text)
    with open(os.path.join(folder, REPORT_CSV), 'w', encoding='utf-8', newline='') as f:
        f.write(csv_text)
    return html_path
