"""
#################################################################
#                                                               #
#                       OCA_MONITOR  GUI                        #
#                   Cerro Armazones Observatory                 #
#                      Araucaria Group, 2023                    #
#               contact person pwielgor@camk.edu.pl             #
#                                                               #
#################################################################
"""
import asyncio
import logging
from asyncio import Lock
from importlib import import_module
import dataclasses

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMainWindow, QGridLayout, QWidget, QTabWidget, QLabel, QToolBar
from PyQt6.QtWidgets import QPushButton, QVBoxLayout
from serverish.base.task_manager import create_task_sync
from serverish.messenger import Messenger, single_read

from oca_monitor.config import settings
from oca_monitor.tab_config_dialog import TabConfigDialog

logger = logging.getLogger('main')

@dataclasses.dataclass
class PageInfo:
    """
    This class is used to store information about each page in the settings file.
    """
    name: str
    auto_interval: int = 10  # seconds
    auto_enabled: bool = False


class AsyncTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pages: dict[str, PageInfo] = {}
        self.tabBar().setVisible(False)
        self.currentChanged.connect(self.checkTabVisibility)
        # # Add 'config' tab with gear icon
        # ico = QIcon.fromTheme('preferences-system')
        # super().addTab(QWidget(), ico, '⚙')

        self.seconds_counter = 0
        self.speed = 2 # default speed - second as defined in settings.toml (default 10)
        self.auto_play = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.eachSecond)
        self.timer.start(1000)  # Timer uruchamiany co 1000 ms (1 sekunda)


    def addTab(self, widget, name, auto_interval=10, auto_enabled=False):
        pageinfo = PageInfo(name=name,
                            auto_interval=auto_interval,
                            auto_enabled=auto_enabled
                            )
        self.pages[name] = pageinfo
        super().addTab(widget, name)
        self.checkTabVisibility()

    def checkTabVisibility(self):
        tab_count = len(self.pages)
        self.tabBar().setVisible(tab_count > 1)

    def eachSecond(self):
        if self.auto_play:
            self.seconds_counter += 1
            time_passed = self.seconds_counter * 10 / self.speed
            current_tab_name = self.tabText(self.currentIndex())
            try:
                pageinfo = self.pages[current_tab_name]
            except KeyError:
                logger.error(f"Page {current_tab_name} not found")
                return
            if time_passed >= pageinfo.auto_interval:
                self.seconds_counter = 0
                next_index = self.currentIndex() + 1
                while next_index != self.currentIndex():
                    if next_index >= self.count():
                        next_index = 0
                        continue
                    # check if next tab is enabled
                    nextpageinfo = self.pages[self.tabText(next_index)]
                    if not nextpageinfo.auto_enabled:
                        next_index = next_index + 1
                    else:
                        break
                self.setCurrentIndex(next_index)
                logger.debug(f"Auto play: {self.tabText(next_index)}")

    def startAutoPlay(self):
        self.auto_play = True
        self.seconds_counter = 100 # let it change immediately

    def stopAutoPlay(self):
        self.auto_play = False



class ConfigurableTabWidget(QWidget):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = AsyncTabWidget()
        self.toolbar = QToolBar()
        self.toolbar.setFixedHeight(30)  # Ustaw wysokość paska narzędziowego
        self.toolbar.layout().setContentsMargins(0, 0, 0, 0)  # Zmniejsz marginesy wewnętrzne paska narzędziowego


        # Dodaj przyciski do paska narzędziowego
        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.config_button = QPushButton("⚙️")

        self.toolbar.addWidget(self.play_button)
        self.toolbar.addWidget(self.stop_button)
        self.toolbar.addWidget(self.config_button)

        self.play_button.clicked.connect(self.playClicked)
        self.stop_button.clicked.connect(self.stopClicked)
        self.config_button.clicked.connect(self.openConfigDialog)

        self.layout.addWidget(self.tab_widget, 1)
        self.updateButtonStyles()

    def playClicked(self):
        self.tab_widget.auto_play = True
        self.tab_widget.startAutoPlay()
        self.updateButtonStyles()

    def stopClicked(self):
        self.tab_widget.auto_play = False
        self.tab_widget.stopAutoPlay()
        self.updateButtonStyles()

    def updateButtonStyles(self):
        if self.tab_widget.auto_play:
            self.play_button.setStyleSheet("background-color: #98FB98;")
            self.stop_button.setStyleSheet("")
        else:
            self.play_button.setStyleSheet("")
            self.stop_button.setStyleSheet("background-color: #FFB6C1;")

    def openConfigDialog(self):
        # Tutaj możesz otworzyć dialog konfiguracyjny
        dialog = TabConfigDialog(self)
        dialog.exec()

    def addTab(self, widget, name, auto_interval=10, auto_enabled=False):
        self.tab_widget.addTab(widget, name, auto_interval=auto_interval, auto_enabled=auto_enabled)

    def showToolbarIfNeeded(self):
        if len(self.tab_widget.pages) > 1:  # If more than one page have been added
            self.layout.addWidget(self.toolbar, 0)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self._config = None

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
                panel_key = f'{i:1d}{j:1d}'  # e.g. '21' for panel in 2nd row, 1st column

                # Each panel has its own tab widget
                # tab_widget = AsyncTabWidget()
                tab_widget = ConfigurableTabWidget(**settings.panels.get(panel_key, {}))
                self.grid_layout.addWidget(tab_widget, i, j)

                # Content of each panel (group of tabs) is defined in the settings also
                # Searches for [<environment>.panels.<i><j>.<tab_name>] in the settings file
                try:
                    for tab_name, page_settings in settings.panels[panel_key].items():
                        auto_interval = page_settings.get('auto_interval', 10)  # seconds
                        auto_enabled = page_settings.get('auto_enabled', True)
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

                        logger.info(f'({i},{j}) new tab "{tab_name}" ({type(widget).__name__}  from {source}.py)')
                        tab_widget.addTab(widget, tab_name, auto_interval=auto_interval, auto_enabled=auto_enabled)
                except LookupError:
                    tab_widget.addTab(QLabel('No pages defined'), '')

                tab_widget.showToolbarIfNeeded()


        self.setCentralWidget(self.central_widget)
        self.setWindowTitle("OCA Monitor")
        #self.resize(*settings.window_size)
        self.setFixedSize(*settings.window_size) 

    _config_reading_in_progress = Lock()

    async def observatory_config(self) -> dict:
        if self._config is None:
            async with self._config_reading_in_progress:
                if self._config is None:
                    self._config, meta = await single_read('tic.config.observatory')
                    logger.info(f'Obtained Observatory Config. Published: {self._config["published"]}')
        return self._config

