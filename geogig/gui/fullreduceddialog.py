import os

# from PyQt5.QtGui import QDoubleValidator
from qgis.PyQt.QtGui import QDoubleValidator

from qgis.utils import iface
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QSizePolicy
from qgis.gui import QgsMessageBar
from qgis.core import Qgis

pluginPath = os.path.dirname(os.path.dirname(__file__))
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'fullreduced.ui'))


class FullReducedDialog(BASE, WIDGET):
    def __init__(self, isFull,screenmap_type,screenmap_factor, parent=None):
        super(FullReducedDialog, self).__init__(parent)
        self.setupUi(self)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.radio_reduced.setChecked(not isFull)
        self.radio_full.setChecked(isFull)
        self.ok = False
        self.edit_oversample.setText( str(screenmap_factor) )
        self.edit_oversample.setValidator( QDoubleValidator(0, 10, 2) );
        if screenmap_type == "WithBBOX":
            self.radio_sm_feature.setChecked(True)
            self.radio_sm_none.setChecked(False)
            self.radio_sm_px.setChecked(False)
        elif screenmap_type == "WithPX":
            self.radio_sm_feature.setChecked(False)
            self.radio_sm_none.setChecked(False)
            self.radio_sm_px.setChecked(True)
        else:
            self.radio_sm_feature.setChecked(False)
            self.radio_sm_none.setChecked(True)
            self.radio_sm_px.setChecked(False)
        self.sm_factor = screenmap_factor
        self.sm_type = screenmap_type

    def accept(self):
        self.fullData = self.radio_full.isChecked()
        self.sm_type = "WithBBOX"
        if self.radio_sm_px.isChecked():
            self.sm_type = "WithPX"
        elif self.radio_sm_none.isChecked():
            self.sm_type = "NONE"
        else:
            self.sm_type = "WithBBOX"
        self.sm_factor = float(self.edit_oversample.text())
        if self.sm_factor <0.1:
            self.sm_factor = 0.1 # dont go too crazy
        if self.sm_factor > 10.0:
            self.sm_factor = 10.0 # dont go too crazy
        self.ok = True
        self.close()
