from qgis.utils import iface
from qgis.PyQt import QtCore, QtWidgets
from qgis.core import *

_currentWindow = iface

def setCurrentWindow(window=None):
    global _currentWindow
    w = window or iface
    _currentWindow = w

def currentWindow():
    return _currentWindow
