from PyQt6.QtWidgets import QCheckBox
from oca_monitor.paths import icon_path


class SlideCheckbox(QCheckBox):
    def __init__(self, parent=None):
        super(SlideCheckbox, self).__init__(parent)
        on_icon = icon_path("switch_on.png")
        off_icon = icon_path("switch_off.png")

        self.setStyleSheet(
            f"QCheckBox::indicator:checked {{ image: url({on_icon}); }}::indicator:unchecked {{ image: url({off_icon}); }}"
        )
        # self.setCheckable(True)
        # self.setStyleSheet("QCheckBox::indicator { width: 20px; height: 20px; }")
