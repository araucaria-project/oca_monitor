import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])


class ExampleWidget(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.initUI(example_parameter)

    def initUI(self, text):
        self.layout = QVBoxLayout(self)

        self.label = QLabel(f"Secret message: {text}", self)
        self.layout.addWidget(self.label)

        # Some async operation
        logger.info("UI setup done")


widget_class = ExampleWidget
