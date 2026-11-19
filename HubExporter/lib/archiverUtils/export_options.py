#  Copyright (c) 2019-2026 Patrick Rainsberry
#  Licensed under the Apache License, Version 2.0. See LICENSE for details.

"""Which Fusion file types the hub exporter handles, and how each is exported."""

# Electronics data file extension -> (factory method on the ElectronicsExportManager, file extension).
# Each electronics document type has exactly one export format. An electronics design (fprj) isn't
# exported on its own: its schematic and board are separate fsch and fbrd files in the same folder.
ELECTRONICS_EXPORTS = {
    'fsch': ('createEagleSchExportOptions', '.sch'),
    'fbrd': ('createEagleBrdExportOptions', '.brd'),
    'flbr': ('createEagleLbrExportOptions', '.lbr'),
}

# Drawing output file extension -> (factory method on the DrawingExportManager, name shown to people).
# DWG export is a preview API, so the factory is checked before it's used.
DRAWING_EXPORTS = {
    '.pdf': ('createPDFExportOptions', 'PDF'),
    '.dwg': ('createDWGExportOptions', 'DWG'),
}

# Data file extensions this add-in can export
DESIGN_FILE_EXTENSION = 'f3d'
DRAWING_FILE_EXTENSION = 'f2d'
