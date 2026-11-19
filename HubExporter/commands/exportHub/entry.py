#  Copyright (c) 2019-2026 Patrick Rainsberry
#  Licensed under the Apache License, Version 2.0. See LICENSE for details.

import html
import os
import webbrowser
from pathlib import Path

import adsk.core
from ...lib import fusionAddInUtils as futil
from ...lib import archiverUtils
from ...lib.hubExport import dialog, inventory
from ...lib.hubExport.ledger import Ledger
from ...lib.hubExport.paths import hub_folder
from ...lib.hubExport.report import write_report
from ...lib.hubExport.runner import run_export
from ... import config
app = adsk.core.Application.get()
ui = app.userInterface


CMD_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_exportHub'
CMD_NAME = 'Export hub'
CMD_Description = ('Exports every file in the hub open in the Data Panel: designs as STEP, drawings as PDF '
                   'and electronics as EAGLE files')

# Specify that the command will be promoted to the panel.
IS_PROMOTED = True

# Resource location for command icons, here we assume a sub folder in this directory named "resources".
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

# Remembers the folder used last time
SETTINGS_PATH = os.path.join(os.path.expanduser('~'), '.fusion-hub-export.json')

# Local list of event handlers used to maintain a reference so
# they are not released and garbage collected.
local_handlers = []

# The hub this dialog will export
dialog_hub = None


# Executed when add-in is run.
def start():
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)
    futil.add_handler(cmd_def.commandCreated, command_created)

    panel = archiverUtils.get_archive_panel()
    control = panel.controls.addCommand(cmd_def)
    control.isPromoted = IS_PROMOTED


# Executed when add-in is stopped.
def stop():
    archiverUtils.remove_command(CMD_ID)


def default_folder() -> str:
    documents = os.path.join(os.path.expanduser('~'), 'Documents')
    base = documents if os.path.isdir(documents) else os.path.expanduser('~')
    return os.path.join(base, config.USER_DIR_NAME)


def command_created(args: adsk.core.CommandCreatedEventArgs):
    futil.log(f'{CMD_NAME} Command Created Event')

    # The command exports the hub open in the Data Panel. In the rare case Fusion
    # can't provide one, open the Data Panel and don't show the dialog.
    global dialog_hub
    dialog_hub = archiverUtils.get_active_hub()
    if dialog_hub is None or dialog_hub.dataProjects.count == 0:
        app.data.isDataPanelVisible = True
        ui.messageBox('Fusion could not find any projects in the active hub.\n\n'
                      f'In the Data Panel, choose the hub you want to export, then run {CMD_NAME} again.', CMD_NAME)
        dialog_hub = None
        return

    inputs = args.command.commandInputs
    folder = dialog.load_last_folder(SETTINGS_PATH, default_folder())

    inputs.addTextBoxCommandInput('hub_name', 'Hub:', html.escape(dialog_hub.name), 1, True)
    inputs.addStringValueInput('output_folder', 'Save to:', folder)
    browse_input = inputs.addBoolValueInput('browse_output_folder', 'Browse', False, '', False)
    browse_input.text = 'Browse...'
    browse_input.tooltip = 'Choose the folder to save to'
    resume_input = inputs.addTextBoxCommandInput('resume_line', '', '', 1, True)
    resume_input.isFullWidth = True
    update_resume_line(inputs)

    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


def update_resume_line(inputs: adsk.core.CommandInputs):
    folder = os.path.expanduser(inputs.itemById('output_folder').value.strip())
    counts = Ledger.peek_counts(hub_folder(folder, dialog_hub.name), dialog_hub.id) if folder and dialog_hub else None
    inputs.itemById('resume_line').text = html.escape(dialog.resume_line(counts))


def command_input_changed(args: adsk.core.InputChangedEventArgs):
    changed_input = args.input
    futil.log(f'{CMD_NAME} Input Changed Event fired from a change to {changed_input.id}')
    inputs = changed_input.parentCommand.commandInputs

    if changed_input.id == 'browse_output_folder':
        folder_input: adsk.core.StringValueCommandInput = inputs.itemById('output_folder')
        folder_dialog = ui.createFolderDialog()
        folder_dialog.title = 'Choose where to save your files'
        if os.path.isdir(folder_input.value):
            folder_dialog.initialDirectory = folder_input.value
        if folder_dialog.showDialog() == adsk.core.DialogResults.DialogOK:
            folder_input.value = folder_dialog.folder
        update_resume_line(inputs)

    elif changed_input.id == 'output_folder':
        update_resume_line(inputs)


def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    # Only allow OK when a folder is given
    args.areInputsValid = bool(args.inputs.itemById('output_folder').value.strip())


# Called when the user clicks OK: checks the folder, reads the hub, confirms, then runs the export.
def command_execute(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Execute Event')

    hub = dialog_hub
    folder = os.path.expanduser(args.command.commandInputs.itemById('output_folder').value.strip())

    problem = dialog.check_writable(folder)
    if problem:
        ui.messageBox(problem, CMD_NAME)
        return
    dialog.save_last_folder(SETTINGS_PATH, folder)

    # The progress file, report and debug log live in the hub's own folder, so exporting two hubs
    # to the same place never mixes them up
    control_folder = hub_folder(folder, hub.name)
    ledger, notice = Ledger.open(control_folder, hub.id, hub.name)
    known_paths = {record.key: record.output_paths for record in ledger.records() if record.output_paths}

    items = read_hub(hub, folder, known_paths)
    ledger.merge(items)
    notices = [notice] if notice else []

    records = ledger.records()
    if not ledger.has_work():
        webbrowser.open(Path(write_report(control_folder, records, hub.name, False, notices)).as_uri())
        ui.messageBox(dialog.nothing_to_export_text(ledger.counts()), CMD_NAME)
        return

    pending_keys = set(ledger.pending_keys())
    pending = [record for record in records if record.key in pending_keys]
    text = dialog.confirmation_text(hub.name, len({record.project for record in pending}), len(pending),
                                    inventory.HAS_DRAWING, inventory.HAS_ELECTRON, notice)
    result = ui.messageBox(text, CMD_NAME, adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                           adsk.core.MessageBoxIconTypes.QuestionIconType)
    if result != adsk.core.DialogResults.DialogYes:
        return

    run_export(hub, control_folder, ledger, items, notices)


def read_hub(hub, folder: str, known_paths: dict) -> list:
    """List the hub's files under a progress dialog. Nothing is opened."""
    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = False
    progress.show(CMD_NAME, 'Reading your hub. This can take a minute.', 0, 1)

    # Fusion opens the dialog asynchronously. If reading finishes before it has opened, hiding
    # it does nothing and it stays open, so let Fusion open it first.
    adsk.doEvents()
    try:
        return inventory.collect_inventory(hub, folder, {}, known_paths)
    finally:
        progress.hide()
        # Fusion only closes the dialog once it gets control back; otherwise it stays on top of
        # the confirmation and blocks its buttons.
        adsk.doEvents()


def command_destroy(args: adsk.core.CommandEventArgs):
    futil.log(f'{CMD_NAME} Command Destroy Event')

    global local_handlers, dialog_hub
    local_handlers = []
    dialog_hub = None
