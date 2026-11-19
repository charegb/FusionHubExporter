"""Runs the export: opens each pending file, exports it, records the result in the ledger.

Fusion runs this on its main thread, so Fusion is busy until it finishes. Between files it checks
for Cancel. Close all documents then cleans up and calls finish().
"""

import os
import traceback
import webbrowser
from pathlib import Path

import adsk.core
import adsk.fusion

from ... import config
from ..archiverUtils import document_utils
from ..archiverUtils.exporter import set_pending_run
from ..archiverUtils.export_options import DRAWING_EXPORTS, ELECTRONICS_EXPORTS
from ..archiverUtils.log_utils import end_log, log, start_log
from .dialog import plural
from .ledger import remove_partial_outputs
from .model import DESIGN, DONE, DRAWING, ELECTRONICS, FAILED, NOT_EXPORTABLE
from .report import write_report

app = adsk.core.Application.get()
ui = app.userInterface

GENERIC_REASON = 'Fusion reported an error while exporting this file'
SAVE_FAILED_MESSAGE = ('Fusion could not save to the export folder, so the export stopped. Check that the folder '
                       'is still there and has room, then run it again to continue.')
STOPPED_MESSAGE = 'Something went wrong in Fusion, so the export stopped. Run it again to continue.'


class ExportError(Exception):
    """A failure with a plain-language reason that is safe to show in the report.

    saved_paths are files that were saved properly before the failure and should be kept.
    """

    def __init__(self, message, saved_paths=()):
        super().__init__(message)
        self.saved_paths = list(saved_paths)


def describe_drawing_failure(saved: list, failed: list) -> str:
    """The reason for a drawing where some of its formats did not export, for example ['PDF'], ['DWG']."""
    if not saved:
        return 'the {} export{} did not complete'.format(' and '.join(failed), 's' if len(failed) > 1 else '')
    return 'the {} was saved, but the {} export did not complete'.format(' and '.join(saved), ' and '.join(failed))


def reason_for(error: Exception) -> str:
    """The reason to record for a file: an ExportError's own text, otherwise a generic one."""
    return str(error) if isinstance(error, ExportError) else GENERIC_REASON


# ------------------------------------------------------------------------------------------------
# Exporting one file (needs Fusion)
# ------------------------------------------------------------------------------------------------

def export_item(item, output_paths: list, keep_version_ids=frozenset(), note_workspace=lambda: None) -> list:
    """Open a data file, export it to its planned path, close it again, and return the paths written.

    Raises ExportError with a plain reason if the file cannot be opened or exported. Documents the
    user already had open are left open. An existing output file is replaced, since a crash can
    leave a half-written one.
    """
    data_file = item.data_file
    document = document_utils.open_data_file(data_file)
    # Opening some documents switches Fusion to another workspace; noting it while the document is open
    # is how a switch is told apart from the user clicking Cancel
    note_workspace()
    if document is None:
        if document_utils.is_other_version_open(data_file):
            raise ExportError('could not be opened because another version of it is open in Fusion')
        raise ExportError('could not be opened')

    try:
        for path in output_paths:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path):
                os.remove(path)

        if item.kind == DESIGN:
            _export_design(output_paths[0])
        elif item.kind == DRAWING:
            _export_drawing(document, output_paths)
        elif item.kind == ELECTRONICS:
            _export_electronics(item.extension, output_paths[0])
        else:
            raise ExportError('this kind of file cannot be exported')

        for path in output_paths:
            if not os.path.exists(path):
                raise ExportError('the export did not produce a file')
        return list(output_paths)

    finally:
        if document_utils.get_version_id(document) not in keep_version_ids:
            document_utils.close_document(document)
        note_workspace()


def _export_design(path: str):
    design = document_utils.get_active_design()
    if design is None:
        raise ExportError('this file is not a design')
    export_mgr = design.exportManager
    if not export_mgr.execute(export_mgr.createSTEPExportOptions(path)):
        raise ExportError('the STEP export did not complete')


def _export_drawing(document, paths: list):
    """Export a drawing to every format in paths (PDF and DWG). Each format is one file with every sheet."""
    import adsk.drawing
    export_mgr = adsk.drawing.DrawingDocument.cast(document).drawing.exportManager

    saved, failed, saved_paths = [], [], []
    for path in paths:
        factory_name, label = DRAWING_EXPORTS[os.path.splitext(path)[1].lower()]
        try:
            if not hasattr(export_mgr, factory_name):
                raise RuntimeError('{} export is not available in this version of Fusion'.format(label))
            options = getattr(export_mgr, factory_name)(path)
            if label == 'PDF':
                options.openPDF = False
            if not export_mgr.execute(options):
                raise RuntimeError('{} export did not complete'.format(label))
            saved.append(label)
            saved_paths.append(path)
        except Exception:
            log('Drawing {} export failed: {}'.format(label, traceback.format_exc()))
            failed.append(label)

    if failed:
        raise ExportError(describe_drawing_failure(saved, failed), saved_paths=saved_paths)


def _export_electronics(extension: str, path: str):
    import adsk.electron
    factory_name = ELECTRONICS_EXPORTS[extension][0]
    product = app.activeProduct
    electronics = (adsk.electron.Board.cast(product) or adsk.electron.Schematic.cast(product)
                   or adsk.electron.Library.cast(product))
    export_mgr = electronics.exportManager if electronics else None
    if export_mgr is None or not hasattr(export_mgr, factory_name):
        raise ExportError('electronics export is not available in this version of Fusion')
    options = getattr(export_mgr, factory_name)(path)
    if options is None or not export_mgr.execute(options):
        raise ExportError('the electronics export did not complete')


# ------------------------------------------------------------------------------------------------
# The run
# ------------------------------------------------------------------------------------------------

def show_progress(total: int, value: int):
    """Show the progress dialog with a Cancel button. Updating it after each file is enough for
    Fusion to handle Cancel while the export runs."""
    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.cancelButtonText = 'Cancel'
    progress.show('Hub export', 'Exporting %v of %m', 0, total)
    progress.progressValue = value
    return progress


def _active_workspace_id():
    return ui.activeWorkspace.id


class _Single:
    """Just enough of a record for remove_partial_outputs to delete one path."""

    def __init__(self, path):
        self.output_paths = [path]


class HubRun:
    """One export run over the pending files of a ledger."""

    def __init__(self, hub_name, control_folder, ledger, items, notices=(), export_fn=None, progress_factory=None,
                 workspace_id=None, open_before_export=frozenset()):
        """control_folder is where the ledger, report and debug log live (the hub's folder in the export)."""
        self.hub_name = hub_name
        self.control_folder = control_folder
        self.ledger = ledger
        self.items = {item.key: item for item in items}
        self.notices = list(notices)
        self.open_before_export = frozenset(open_before_export)
        self.export_fn = export_fn or (
            lambda item, paths, note: export_item(item, paths, self.open_before_export, note))
        self.progress_factory = progress_factory or show_progress
        self.workspace_id = workspace_id or _active_workspace_id
        self.cancelled = False
        self.fatal_message = ''
        self.report_path = ''
        self.workspaces_seen = set()

    def _note_workspace(self):
        try:
            self.workspaces_seen.add(self.workspace_id())
        except RuntimeError:
            pass

    def _write_report(self):
        try:
            self.report_path = write_report(self.control_folder, self.ledger.records(), self.hub_name,
                                            self.cancelled or bool(self.fatal_message), self.notices)
        except OSError:
            log('Could not write the report: ' + traceback.format_exc())

    def run(self):
        keys = self.ledger.pending_keys()
        total = len(keys)

        os.makedirs(self.control_folder, exist_ok=True)
        start_log(self.control_folder, ['Hub: {}'.format(self.hub_name), 'Files to export: {}'.format(total)])

        # A report right away, so the user has one even if Fusion stops during this run
        self._write_report()

        progress = None
        try:
            self.ledger.begin_run()
            progress = self.progress_factory(total, 0)
            self.workspaces_seen = {self.workspace_id()}

            for index, key in enumerate(keys):
                if progress.wasCancelled:
                    # Opening some documents, such as electronics, switches Fusion to another workspace
                    # and back, which closes the dialog and reports it as cancelled. Only a cancel with
                    # no workspace change since the dialog was shown came from the user.
                    if len(self.workspaces_seen) == 1:
                        self.cancelled = True
                        log('Cancelled after {} of {} files'.format(index, total))
                        break
                    progress.hide()
                    progress = self.progress_factory(total, index)
                    self.workspaces_seen = {self.workspace_id()}

                record = self.ledger.get(key)
                where = '{}/{}'.format(record.project, record.project_path).replace('%', '')
                progress.message = 'Exporting %v of %m: {}'.format(where)
                progress.progressValue = index

                self.ledger.mark_in_progress(key)
                try:
                    paths = self.export_fn(self.items[key], record.output_paths, self._note_workspace)
                except Exception as error:  # one bad file must never stop the run
                    log('Failed: {}\n{}'.format(where, traceback.format_exc()))
                    keep = set(getattr(error, 'saved_paths', ()))
                    for path in record.output_paths:
                        if path not in keep:
                            remove_partial_outputs(_Single(path))
                    self.ledger.mark_failed(key, reason_for(error))
                else:
                    self.ledger.mark_done(key, paths)
                self._note_workspace()

            else:
                progress.progressValue = total

        except Exception as error:
            log('The export stopped: ' + traceback.format_exc())
            self.fatal_message = SAVE_FAILED_MESSAGE if isinstance(error, OSError) else STOPPED_MESSAGE

        finally:
            if progress is not None:
                try:
                    progress.hide()
                except Exception:
                    pass

        try:
            self.ledger.end_run(True)
        except OSError:
            self.fatal_message = self.fatal_message or SAVE_FAILED_MESSAGE
        self._write_report()
        end_log(['Exported: {}'.format(self.ledger.counts()[DONE])])

    def finish(self):
        """Show what happened and open the report. Called once Close all documents is done."""
        text = summary_text(self.ledger.counts(), self.cancelled, self.fatal_message, self.ledger.has_work(),
                            self.report_path)
        ui.messageBox(text, 'Hub export')
        if self.report_path:
            webbrowser.open(Path(self.report_path).as_uri())


def summary_text(counts: dict, cancelled: bool, fatal_message: str, has_work: bool, report_path: str) -> str:
    """The message shown when a run ends."""
    lines = ['{} exported.'.format(plural(counts[DONE], 'file'))]
    if counts[FAILED]:
        lines.append('{} could not be exported.'.format(plural(counts[FAILED], 'file')))
    if counts[NOT_EXPORTABLE]:
        lines.append('{} not exported (for example uploaded files that are not Fusion files).'.format(
            plural(counts[NOT_EXPORTABLE], 'file')))
    if fatal_message:
        lines.append(fatal_message)
    elif cancelled:
        lines.append('The export was stopped. Run it again and choose the same folder to continue.')
    elif has_work:
        lines.append('Some files are still waiting. Run it again and choose the same folder to continue.')
    if report_path:
        lines.append('Your report is saved in the export folder and is opening now.')
    return '\n\n'.join(lines)


def run_export(hub, control_folder, ledger, items, notices=()):
    """Run the export, then start Close all documents, which calls finish() when it is done."""
    run = HubRun(hub.name, control_folder, ledger, items, notices,
                 open_before_export=document_utils.get_open_version_ids())
    set_pending_run(run)
    run.run()
    ui.commandDefinitions.itemById(config.CLOSE_ALL_CMD_ID).execute()
