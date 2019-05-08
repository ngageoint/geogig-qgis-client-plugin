import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import (QDialog,
                                 QHBoxLayout,
                                 QTableWidgetItem,
                                 QLabel,
                                 QTextEdit,
                                 QListWidgetItem
                                )
from qgis.PyQt.QtGui import QFont, QIcon

from qgis.core import  Qgis, QgsSymbol, QgsSingleSymbolRenderer, QgsGeometry, QgsFeature, QgsProject
from qgis.gui import QgsMapCanvas, QgsMapToolPan
from qgis.utils import iface

from geogig.extlibs.qgiscommons2.layers import loadLayerNoCrsDialog
from geogig.geogigwebapi.connector import GeogigError

pluginPath = os.path.split(os.path.dirname(__file__))[0]
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'versionsviewer.ui'))

class VersionViewerDialog(BASE, WIDGET):

    def __init__(self, geogiglayer, fid):
        super(VersionViewerDialog, self).__init__(iface.mainWindow())
        self.geogiglayer = geogiglayer
        self.fid = fid
        self.layer = None
        self.setupUi(self)

        self.listWidget.itemClicked.connect(self.commitClicked)

        horizontalLayout = QHBoxLayout()
        horizontalLayout.setSpacing(0)
        horizontalLayout.setMargin(0)
        self.mapCanvas = QgsMapCanvas()
        self.mapCanvas.setCanvasColor(Qt.white)
        horizontalLayout.addWidget(self.mapCanvas)
        self.mapWidget.setLayout(horizontalLayout)
        self.panTool = QgsMapToolPan(self.mapCanvas)
        self.mapCanvas.setMapTool(self.panTool)

        path = geogiglayer.layername + "/" + fid
        ids, commits = geogiglayer.server.log(geogiglayer.user, geogiglayer.repo, "master", path)
        if commits:
            for commit in commits.values():
                item = CommitListItem(commit, geogiglayer, fid)
                self.listWidget.addItem(item)
        else:
            raise GeogigError("The selected feature is not versioned yet")

    def commitClicked(self):
        feature = self.listWidget.currentItem().feature()
        geom = feature.geometry()
        attributes = feature.attributes()
        self.attributesTable.setRowCount(len(attributes))
        props = [f.name() for f in feature.fields()]
        for idx in range(len(props)):
            value = attributes[idx]
            font = QFont()
            font.setBold(True)
            font.setWeight(75)
            item = QTableWidgetItem(props[idx])
            item.setFont(font)
            self.attributesTable.setItem(idx, 0, item)
            self.attributesTable.setItem(idx, 1, QTableWidgetItem(str(value)))

        self.attributesTable.resizeRowsToContents()
        self.attributesTable.horizontalHeader().setMinimumSectionSize(150)
        self.attributesTable.horizontalHeader().setStretchLastSection(True)

        self.removeLayer()
        types = ["Point", "LineString", "Polygon"]
        geomtype = types[int(geom.type())]
        self.layer = loadLayerNoCrsDialog(geomtype + "?crs=EPSG:4326", "temp", "memory")
        pr = self.layer.dataProvider()
        feat = QgsFeature()
        feat.setGeometry(geom)
        pr.addFeatures([feat])
        self.layer.updateExtents()
        self.layer.selectAll()
        self.layer.setExtent(self.layer.boundingBoxOfSelected())
        self.layer.invertSelection()
        symbol = QgsSymbol.defaultSymbol(self.layer.geometryType())
        symbol.setColor(Qt.green)
        symbol.setOpacity(0.5)
        self.layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        self.mapCanvas.setRenderFlag(False)
        self.mapCanvas.setLayers([self.layer])
        QgsProject.instance().addMapLayer(self.layer, False)
        self.mapCanvas.setExtent(self.layer.extent())
        self.mapCanvas.setRenderFlag(True)
        self.mapCanvas.refresh()

    def removeLayer(self):
        if self.layer is not None:
            QgsProject.instance().removeMapLayers([self.layer.id()])

    def closeEvent(self, evt):
        self.removeLayer()
        evt.accept()

class CommitListItem(QListWidgetItem):

    icon = QIcon(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "ui", "resources", "person.png"))

    def __init__(self, commit, geogiglayer, fid):
        QListWidgetItem.__init__(self)
        self.commit = commit
        self._feature = None
        self.geogiglayer = geogiglayer
        self.fid = fid
        self.setText("%s (by %s)" % (commit["message"].splitlines()[0], commit["author"]["name"]))

    def feature(self):
        if self._feature is None:
            self._feature = self.geogiglayer.server.feature(self.geogiglayer.user, self.geogiglayer.repo,
                                                            self.geogiglayer.layername, self.fid, self.commit["id"])
        return self._feature
