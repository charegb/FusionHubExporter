#  Copyright (c) 2019-2026 Patrick Rainsberry
#  Licensed under the Apache License, Version 2.0. See LICENSE for details.

"""Holds the export that the Close all documents command is cleaning up after.

After an export, Close all documents closes any documents still loaded, such as designs an
assembly referenced, and then calls finish_export so the summary is shown once nothing is open.
Showing a message box while exported documents are still open can fail.
"""

# The run that Close all documents is cleaning up after, or None. It has open_before_export
# (the version ids to leave open) and finish().
pending_run = None


def set_pending_run(run):
    global pending_run
    pending_run = run


def get_keep_version_ids():
    """Return the documents Close all documents should leave open: the ones the user had open
    before the export it's cleaning up after, or none when it isn't cleaning up after an export."""
    return pending_run.open_before_export if pending_run else frozenset()


def finish_export():
    """Called when Close all documents is done. Shows the summary of the export it cleaned up after."""
    global pending_run
    if pending_run:
        run, pending_run = pending_run, None
        run.finish()
