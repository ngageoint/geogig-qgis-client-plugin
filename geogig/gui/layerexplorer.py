import os 
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QEvent, QSize
from qgis.PyQt.QtWidgets import QVBoxLayout, QSizePolicy
from qgis.utils import iface
from qgis.core import QgsProject
from qgis.gui import QgsMapCanvas, QgsMapToolPan, QgsMessageBar

from geogig.gui.historyviewer import HistoryTreeWrapper, HistoryTree
from geogig.layers.geogiglivelayer import GeogigLiveLayer
from geogig.gui.commitgraph import CommitGraph
from geogig.styles import setStyle
from geogig.gui.progressbar import setCurrentWindow

pluginPath = os.path.split(os.path.dirname(__file__))[0]

WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'layerexplorer.ui'))

class MessageBar(QgsMessageBar):
    def __init__(self, parent=None):
        super(MessageBar, self).__init__(parent)
        self.parent().installEventFilter(self)

    def showEvent(self, event):
        self.resize(QSize(self.parent().geometry().size().width(), self.height()))
        self.move(0, 0)
        self.raise_()

    def eventFilter(self, object, event):
        if event.type() == QEvent.Resize:
            self.showEvent(None)

        return super(MessageBar, self).eventFilter(object, event)

class LayerExplorer(BASE, WIDGET):

    def __init__(self, server, user, repo, graph, layername):
        super(LayerExplorer, self).__init__(None)
        self.user = user
        self.server = server
        self.repo = repo
        self.layername = layername
        self.layer = None
        self.extent = None
        self.renderer = None
        self.graph = graph

        self.setupUi(self)

        self.history = HistoryTree(self)
        self.history.updateContent(self.server, self.user, self.repo, self.graph, self.layername)
        historyTreeWrapper = HistoryTreeWrapper(self.history)
        layout = QVBoxLayout()
        layout.setMargin(0)
        layout.addWidget(historyTreeWrapper)
        self.historyWidget.setLayout(layout)
        layout = QVBoxLayout()
        layout.setMargin(0)
        self.canvas = QgsMapCanvas()
        self.canvas.setCanvasColor(Qt.white)
        self.panTool = QgsMapToolPan(self.canvas)
        self.canvas.setMapTool(self.panTool)
        layout.addWidget(self.canvas)        
        self.mapWidget.setLayout(layout)
        self.canvas.extentsChanged.connect(self.refreshLayer)

        self.history.currentItemChanged.connect(self.itemChanged)

        self.resize(900, 500)
        self.setWindowTitle("Layer Explorer [{}]".format(layername))
        self.setWindowFlags(Qt.Window)

        setCurrentWindow(self)

        self.bar = MessageBar(self.canvas)
        #self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        #self.canvas().insertWidget(0, self.bar)

    def messageBar(self):
        return self.bar

    def refreshLayer(self):
        if self.layer is not None:
            self.layer.refresh(forceRefresh = False)

    def itemChanged(self):        
        item = self.history.currentItem()
        if item is not None:
            item.setSelected(True)
            self.removeLayer()
            self.layer = GeogigLiveLayer(self.server, self.user, self.repo, self.layername, item.ref, canvas = self.canvas)        
            layer = self.layer.layer
            if self.renderer is None:
                setStyle(self.layer)
                self.renderer = layer.renderer().clone()
            else:
                layer.setRenderer(self.renderer.clone())
            QgsProject.instance().addMapLayer(layer, False)
            self.canvas.setLayers([layer])
            if self.extent is None:
                self.extent = layer.extent()
                self.canvas.setExtent(self.extent)            
            self.canvas.refresh()        

    def removeLayer(self):
        if self.layer is not None:
            QgsProject.instance().removeMapLayer(self.layer.layer.id())
            self.layer = None

    def closeEvent(self, evt):
        self.removeLayer()
        setCurrentWindow()
        evt.accept()