
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMenu, QAction, QMessageBox
from qgis.core import QgsVectorLayer, QgsRectangle, QgsFeatureRequest, Qgis
from qgis.gui import QgsMapTool, QgsMessageBar

from qgis.utils import iface
#from geogig.gui.dialogs.blamedialog import BlameDialog
from geogig.gui.versionsviewer import VersionViewerDialog
from geogig.layers import getWrappingGeogigLayer
from geogig.utils import GEOGIGID_FIELD
from geogig.geogigwebapi.connector import GeogigError

class MapToolGeoGigInfo(QgsMapTool):

    def __init__(self, canvas):
        QgsMapTool.__init__(self, canvas)
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, e):
        layer = iface.activeLayer()
        if layer is None or not isinstance(layer, QgsVectorLayer):
            iface.messageBar().pushMessage("No layer selected or the current active layer is not a valid vector layer",
                                                  level = Qgis.Warning, duration = 5)
            return
        geogiglayer = getWrappingGeogigLayer(layer)
        if geogiglayer is None:
            iface.messageBar().pushMessage("The current active layer is not being tracked as part of a GeoGig repo",
                                                  level = Qgis.Warning, duration = 5)
            return

        point = self.toMapCoordinates(e.pos())
        searchRadius = self.canvas().extent().width() * .01;
        r = QgsRectangle()
        r.setXMinimum(point.x() - searchRadius);
        r.setXMaximum(point.x() + searchRadius);
        r.setYMinimum(point.y() - searchRadius);
        r.setYMaximum(point.y() + searchRadius);

        r = self.toLayerCoordinates(layer, r);

        fit = layer.getFeatures(QgsFeatureRequest().setFilterRect(r).setFlags(QgsFeatureRequest.ExactIntersect));
        fid = None
        try:
            feature = next(fit)
            fid = feature[GEOGIGID_FIELD]
            if fid is None:
                return
        except StopIteration as e:
            return

        self.versions(geogiglayer, fid)
        
    def versions(self, geogiglayer, fid):
        try:
            path = geogiglayer.layername + "/" + fid
            dlg = VersionViewerDialog(geogiglayer, fid)
            dlg.exec_()
        except GeogigError as e:
            QMessageBox.critical(self.parent(), "Error", "%s" % e)


