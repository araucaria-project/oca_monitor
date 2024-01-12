style_sheet = """
    QWidget {
        background-color: #fff;
        color: #333;
    }
    QPushButton {
        background-color: #f5f5f5;
        border: 1px solid #dde;
        padding: 6px;
        border-radius: 3px;
    }
    QPushButton:hover {
        background-color: #eee;
    }
    QPushButton:pressed {
        background-color: #e0e0e0;
    }
    QTabWidget::pane {
        border: 1px solid #aaf;
    }
    QTabBar::tab {
        background: #fff;
        padding: 10px;
        margin: 1px;
        border-radius: 4px;
        border: 1px solid #eef;
    }
    QTabBar::tab:selected {
        background: #f7f7f7;
        color: #333;
    }
    QTabBar::tab:!selected {
        background: #fafafa;
        color: #777;
    }
    QLineEdit {
        border: 1px solid #dde;
        padding: 4px;
        background: #fff;
    }
    QLineEdit:focus {
        border-color: #cccccc;
    }
    QToolBar {
        border: none;
        background: #f5f5ff;
    }
    QScrollBar:vertical {
        border: none;
        background: #f5f5f5;
        width: 10px;
    }
    QScrollBar::handle:vertical {
        background: #dde;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background: #ccc;
    }
    QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
        background: none;
    }
"""