import sys
from PyQt5.QtCore import *
from PyQt5.QtWebEngineWidgets import *
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

web = QWebEngineView()
web.load(QUrl("http://www.users.camk.edu.pl/pwielgor"))
web.show()

sys.exit()
