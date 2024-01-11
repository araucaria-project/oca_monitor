#!/usr/bin/env python

#################################################################
#                                                               #
#                       OCA_MONITOR  GUI                        #
#                   Cerro Armazones Observatory                 #
#                      Araucaria Group, 2023                    #
#               contact person pwielgor@camk.edu.pl             #
#                                                               #
#################################################################

import logging
from importlib import import_module

from PyQt5.QtWidgets import QMainWindow, QGridLayout, QWidget, QTabWidget, QLabel

from oca_monitor.config import settings

logger = logging.getLogger('main')



class AsyncTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabBar().setVisible(False)
        self.currentChanged.connect(self.checkTabVisibility)

    def addTab(self, widget, name):
        super().addTab(widget, name)
        self.checkTabVisibility()

    def checkTabVisibility(self):
        tab_count = self.count()
        self.tabBar().setVisible(tab_count > 1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.central_widget = QWidget()
        # We will divide the window into a grid of panels
        self.grid_layout = QGridLayout(self.central_widget)

        # The relative sizes of  rows and columns are defined in the settings
        rows, cols = settings.panel_rows, settings.panel_columns

        # Set sizes of rows and columns
        for i, size in enumerate(cols):
            self.grid_layout.setColumnStretch(i, size)

        for i, size in enumerate(rows):
            self.grid_layout.setRowStretch(i, size)

        # Iterate over panels and add tabs to each panel
        for i in range(len(rows)):
            for j in range(len(cols)):
                # Each panel has its own tab widget
                tab_widget = AsyncTabWidget()
                self.grid_layout.addWidget(tab_widget, i, j)

                # Content of each panel (group of tabs) is defined in the settings also
                # Searches for [<environment>.panels.<i><j>.<tab_name>] in the settings file
                panel_key = f'{i:1d}{j:1d}'
                try:
                    for tab_name, page_settings in settings.panels[panel_key].items():
                        auto_interval = page_settings.get('auto_interval', 0)  # seconds
                        source = page_settings.get('source', None)
                        # Create a tab for each tab name from <source>.py

                        # dynamically import module from oca_monitor.pages.<source>.py
                        module = import_module(f"oca_monitor.pages.{source}")
                        # each <source>.py file should have a widget_class defined e.g.:
                        # widget_class = MyWidget
                        widget_class = getattr(module, "widget_class")
                        # create an instance of the widget_class
                        # e.g. widget = MyWidget(**page_settings)
                        # The constructor of the widget_class should accept **kwargs
                        widget = widget_class(main_window = self, **page_settings)

                        logger.info(f'Adding {type(widget)} tab "{tab_name}" to panel ({i},{j}) from source {source}.py')
                        tab_widget.addTab(widget, tab_name)
                except LookupError:
                    tab_widget.addTab(QLabel('No pages defined'), '')


        self.setCentralWidget(self.central_widget)
        self.setWindowTitle("OCA Monitor")
        self.resize(*settings.window_size)

