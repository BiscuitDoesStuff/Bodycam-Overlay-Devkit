"""About tab -- credits and license info."""
from tkinter import ttk

import ui_theme as ui
from ui_theme import PAD_LG


class AboutTab(ttk.Frame):
    """Credits/license info -- see docs/DOCUMENTATION.md §5.6 for why this tab
    can't be made "tamper-proof" and what actually enforces attribution."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        ui.label(self, text="Bodycam Overlay -- Bodycam Devkit Overlay", header=True).pack(anchor="w", padx=PAD_LG, pady=(PAD_LG + 4, 0))
        ui.label(self, text="A standalone external control panel for Bodycam -- "
                             "not injected into the game process.", muted=True, wraplength=600,
                 justify="left").pack(anchor="w", padx=PAD_LG, pady=(2, PAD_LG))

        ui.label(self, text="Original project", bold=True).pack(anchor="w", padx=PAD_LG, pady=(0, 2))
        ui.label(self, text="Bodycam Overlay, created by clutch5.9. Licensed under the MIT "
                             "License -- the original copyright notice is preserved in LICENSE ",
                 muted=True, wraplength=600, justify="left").pack(anchor="w", padx=PAD_LG, pady=(0, PAD_LG))

        ui.label(self, text="This fork", bold=True).pack(anchor="w", padx=PAD_LG, pady=(0, 2))
        ui.label(self, text="BDT Overlay Fork, maintained by BiscuitDoesStuff --\n"
                             "github.com/BiscuitDoesStuff/BDT-Overlay-Fork\n"
                             "Builds on clutch5.9's original with its own improvements!",
                 muted=True, wraplength=600, justify="left").pack(anchor="w", padx=PAD_LG, pady=(0, PAD_LG))

        ui.label(self, text="Third-party components:", bold=True).pack(anchor="w", padx=PAD_LG, pady=(0, 2))
        ui.label(self, text="RE-UE4SS -- MIT License, Copyright (c) 2022 Narknon\n"
                             "(bundled under src/ue4ss_bundle/, see its own LICENSE file)",
                 muted=True, justify="left").pack(anchor="w", padx=PAD_LG, pady=(0, PAD_LG))

        ui.label(self, text="Docs: docs/DOCUMENTATION.md in the project folder explains the Console/"
                             "Shell tabs, the plugin format, and troubleshooting.",
                 muted=True, wraplength=600, justify="left").pack(anchor="w", padx=PAD_LG)


