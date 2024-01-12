style_sheet =  """
    QWidget {
        background-color: #f0f0f0;
        color: #333;
    }
    QPushButton {
        background-color: #e6e6e6;
        border: 1px solid #bbb;
        padding: 6px;
        border-radius: 3px;
    }
    QPushButton:hover {
        background-color: #dcdcdc;
    }
    QPushButton:pressed {
        background-color: #cccccc;
    }
    QTabWidget::pane {
        border: 1px solid #aaa;
    }
    QTabBar::tab {
        background: #f9f9f9;
        padding: 5px 10px;
        margin: 1px;
        border-radius: 4px;
        border: 1px solid #ddd;
        min-height: 20px;  
    }
    QTabBar::tab:selected {
        background: #fff;
        color: #333;
    }
    QTabBar::tab:!selected {
        background: #eeeeee;
        color: #777;
    }
    QLineEdit {
        border: 1px solid #ccc;
        padding: 4px;
        background: #fff;
    }
    QLineEdit:focus {
        border-color: #7ab0d4;
    }
    QToolBar {
        border: none;
        background: #f1f1f1;
    }
    QScrollBar:vertical {
        border: none;
        background: #f1f1f1;
        width: 10px;
    }
    QScrollBar::handle:vertical {
        background: #ccc;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background: #bbb;
    }
    QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
        background: none;
    }
"""