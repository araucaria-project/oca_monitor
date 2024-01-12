from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QSlider, QLabel, QHBoxLayout, QPushButton, QGroupBox

from oca_monitor.controls import SlideCheckbox
from oca_monitor.paths import icon_path

class TabConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tabs Auto-rotation Settings")
        self.layout = QVBoxLayout(self)


        self.tabs_info = parent.tab_widget.pages

        self.tabs_group_box = QGroupBox("Tabs taking part in auto-rotation")
        self.tabs_layout = QVBoxLayout()

        for name, page_info in self.tabs_info.items():
            checkbox = SlideCheckbox(name)
            checkbox.setChecked(page_info.auto_enabled)
            checkbox.stateChanged.connect(lambda state, x=name: self.updateTabEnabled(x, state))
            self.tabs_layout.addWidget(checkbox)

        self.tabs_group_box.setLayout(self.tabs_layout)
        self.layout.addWidget(self.tabs_group_box)

        self.speed_label = QLabel(f"Speed: {self.speed}s")
        self.layout.addWidget(self.speed_label)

        self.speed_slider = QSlider()
        self.speed_slider.setOrientation(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(1)
        self.speed_slider.setMaximum(60)
        self.speed_slider.setMinimumWidth(300)  # Zwiększ minimalną szerokość slidera
        self.speed_slider.setValue(self.speed)
        self.speed_slider.valueChanged.connect(self.updateSpeed)
        self.layout.addWidget(self.speed_slider)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        self.layout.addWidget(self.close_button)

    @property
    def speed(self):
        return self.parent().tab_widget.speed

    @speed.setter
    def speed(self, value):
        self.parent().tab_widget.speed = value
        # self.speed_slider.setValue(value)
        self.speed_label.setText(f"Speed: {value}s")

    def updateTabEnabled(self, name, state):
        self.tabs_info[name].auto_enabled = state == Qt.Checked

    def updateSpeed(self, speed):
        self.speed = speed

