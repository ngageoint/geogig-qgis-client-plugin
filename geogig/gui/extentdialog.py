import os
from qgis.utils import iface
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QSizePolicy
from qgis.gui import QgsMessageBar
from qgis.core import Qgis

pluginPath = os.path.dirname(os.path.dirname(__file__))
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'extentdialog.ui'))

class ExtentDialog(BASE, WIDGET):

    # None - don't do anything (normal)
    # ExtentDialog.TEST_CASE_OVERRIDE = {"radioRestrictedExtent":True, "radioFullExtent":False, "Extent":[xmin,ymin,xmax,ymax]}
    # ExtentDialog.TEST_CASE_OVERRIDE = {"radioRestrictedExtent":False, "radioFullExtent":False, "Extent":None}

    TEST_CASE_OVERRIDE = None

    def __init__(self, parent=None):
        super(ExtentDialog, self).__init__(parent)
        self.setupUi(self)
        self.buttonCanvasExtent.clicked.connect(self.useCanvasExtent)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.radioFullExtent.toggled.connect(self.toggled)

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().insertWidget(0, self.bar)
        self.extent = None
        self.ok = False

        if ExtentDialog.TEST_CASE_OVERRIDE is not None:
            self.radioRestrictedExtent.setChecked(ExtentDialog.TEST_CASE_OVERRIDE["radioRestrictedExtent"])
            self.radioFullExtent.setChecked(ExtentDialog.TEST_CASE_OVERRIDE["radioFullExtent"])
            if ExtentDialog.TEST_CASE_OVERRIDE["extent"] is not None:
                self.textXMin.setText( str(ExtentDialog.TEST_CASE_OVERRIDE["extent"][0]))
                self.textYMin.setText(  str(ExtentDialog.TEST_CASE_OVERRIDE["extent"][1]))
                self.textXMax.setText(  str(ExtentDialog.TEST_CASE_OVERRIDE["extent"][2]))
                self.textYMax.setText(  str(ExtentDialog.TEST_CASE_OVERRIDE["extent"][3]))
            self.accept()

    def exec_(self):
        if ExtentDialog.TEST_CASE_OVERRIDE is None:
            super(ExtentDialog, self).exec_()

    def toggled(self):
        checked = self.radioRestrictedExtent.isChecked()
        self.widgetRestrictedExtent.setEnabled(checked)

    def useCanvasExtent(self):
        self.radioRestrictedExtent.setChecked(True)
        self.radioFullExtent.setChecked(False)
        self.setExtent(iface.mapCanvas().extent())

    def setExtent(self, extent):
        self.textXMin.setText(str(extent.xMinimum()))
        self.textYMin.setText(str(extent.yMinimum()))
        self.textXMax.setText(str(extent.xMaximum()))
        self.textYMax.setText(str(extent.yMaximum()))
       # iface.mapCanvas().setMapTool(self.prevMapTool)

    def accept(self):
        def _check(w):
            try:
                v = w.text()
                return float(v)
            except ValueError:
                raise Exception("Wrong Value: " + v)

        if self.radioFullExtent.isChecked():
            self.extent = None
            self.ok = True
        else:
            widgets = [self.textXMin, self.textYMin, self.textXMax, self.textYMax]
            try:
                self.extent = [_check(widget) for widget in widgets]
                self.ok = True
            except Exception as e:
                self.extent = None
                self.bar.pushMessage("Error", str(e), level=Qgis.Warning)
                return

        self.close()



