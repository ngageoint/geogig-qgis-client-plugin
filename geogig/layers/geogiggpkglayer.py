import struct
import traceback
import uuid

from geogig.conflicts import *
from geogig.layers.geogiglayer import *
from geogig.geogigwebapi.connector import GeogigAuthException, GeogigError
from geogig.geopkgtools import *
from geogig.gui.constellationviewer import *
from geogig.gui.diffviewer import DiffViewerDialog
from geogig.gui.extentdialog import ExtentDialog
from geogig.protobuff.queryforlayerproto import QueryForLayerProto
from geogig.protobuff.proto2qgis import FeatureWriter
from geogig.utils import GEOGIGID_FIELD, hideGeogigidField
from geogig.styles import setStyle

from qgis.PyQt.QtCore import QThread, pyqtSignal, QObject, QTimer
from qgiscommons2.gui import startProgressBar, closeProgressBar, setProgressText, execute
from qgiscommons2.settings import pluginSetting

from qgis.core import QgsMessageLog, QgsVectorLayer
from qgis.utils import iface

class GeogigGpkgLayer(GeogigLayer):
    def __init__(self, server, user, repo, layername, commitid, layer=None, extent=None):
        super().__init__(server, user, repo, layername, commitid, layer, extent)
        self.valid = True
        self.alwaysFullDetail = True
        self.screenmap_type = "NONE"
        self.screenmap_factor = 1.0
        if layer is not None:
            self.gpkgPath = simplifyGeoPKGFname(layer.source())
            self.commitid = getMetadataValue(self.gpkgPath, self.GEOGIG_COMMITID)
            self.layer = layer
            self.loadChanges()
            self.setupLayer()
            hideGeogigidField(self.layer)
            setStyle(self)
            self.layer.beforeRollBack.connect(self.beforeRollBack)
            self.layer.styleChanged.connect(self.styleChanged)
            self.valid = True
            self.rolledback = False
        else:
            self.gpkgPath = self._gpkgPath()
            try:
                self.populate()
            except:
                QgsMessageLog.logMessage(traceback.format_exc(), level=Qgis.Critical)

    def beforeRollBack(self):
        self.rolledback = True

    def setupLayer(self):
        self.layer.setTitle("GeoGig GeoPKG Layer")
        super().setupLayer()
        if self.layer is not None:
            self.changeExtentAction = QAction("Change layer extent...", iface)
            self.changeExtentAction.triggered.connect(self.changeExtent)
            iface.addCustomActionForLayerType(self.changeExtentAction, "GeoGig", QgsMapLayer.VectorLayer, False)
            iface.addCustomActionForLayer(self.changeExtentAction , self.layer)

            self.updateRevisionAction = QAction("Update to latest revision from server...", iface)
            self.updateRevisionAction.triggered.connect(self.updateRevision)
            iface.addCustomActionForLayerType(self.updateRevisionAction, "GeoGig", QgsMapLayer.VectorLayer, False)
            iface.addCustomActionForLayer(self.updateRevisionAction, self.layer)
            self.layer.beforeRollBack.connect(self.beforeRollBack)
        self.localChangesAvailable.emit(self.hasLocalChanges())

    def cleanup(self):
        super().cleanup()
        iface.removeCustomActionForLayerType(self.changeExtentAction)
        iface.removeCustomActionForLayerType(self.updateRevisionAction)

    def updateRevision(self):
        if self.hasLocalChanges():
            QMessageBox.information(iface.mainWindow(), 'Cannot Update From Server',
                                    "You have local changes - please commit or revert them before updating from server.")
            return
        if self.layer.isEditable():
            QMessageBox.information(iface.mainWindow(), 'Cannot Update From Server',
                                    "Please stop editing before updating from server.")
            return

        currentcommitId  = self.server.commitidForBranch(self.user, self.repo, "master")
        if currentcommitId==self.commitid:
            QMessageBox.information(iface.mainWindow(), 'Already up-to-date',
                                    "No changes available from server.")
            return

        self._afterCommitting()

    def showChanges(self):
        if not self.hasLocalChanges():
            iface.messageBar().pushMessage("", "The layer has no local changes", level=Qgis.Info, duration=5)
            return
        changes = {self.layername: getChangeSet(self.gpkgPath)}
        dialog = DiffViewerDialog(changes)
        dialog.exec_()

    def revertChanges(self):
        execute(lambda: revertToBaseRevision(self.gpkgPath,self.layername))
        self.deletedFeatures = []
        self.modifiedFeatures = []
        self.addedFeatures = []
        self.localChangesAvailable.emit(self.hasLocalChanges())
        self.layer.triggerRepaint()

    def changeExtent(self):
        if self.hasLocalChanges():
            QMessageBox.information(iface.mainWindow(),'Cannot Change Extent',
                                    "You have local changes - please commit or revert them before changing the extent.")
            return
        if self.layer.isEditable():
            QMessageBox.information(iface.mainWindow(), 'Cannot Change Extent',
                                    "Please stop editing before changing the extent.")
            return
        dlg = ExtentDialog(iface.mainWindow())
        dlg.exec_()
        if dlg.ok:
            if dlg.extent is None:
                self.extent = self.server.layerExtent(self.user, self.repo, self.layername, self.commitid)
                self.layer.setExtent(QgsRectangle(*self.extent))
            else:
                rect = self.extentToLayerCrs(QgsRectangle(*dlg.extent))
                self.layer.setExtent(rect)
                self.extent = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]

            self.backgroundingDownloader = BackgroundLayerDownload(self.server, self.user, self.repo,
                                                                   self.layername, self.commitid, extent=self.extent,
                                                                   filepath=self.gpkgPath)
            self.backgroundingDownloader.finished.connect(self.newExtentDataReceived)
            self.backgroundingDownloader.start()


    def newExtentDataReceived(self,layer,fname):
        # reuse layer we already have, delete the new one!
        import sip
        sip.delete(layer)
        del layer

        self.setMetadataInGpkg()
        self.layer.dataProvider().dataChanged.emit()
        self.layer.triggerRepaint()
        self.setupAbstract()

    def saveChanges(self):
        return

    def loadChanges(self):
        changes = getChangeSet(self.gpkgPath)
        # reset (we are doing a full change load)
        self.addedFeatures = []
        self.modifiedFeatures = []
        self.deletedFeatures = []

        adds = [f["ID"] for f in changes if f['geogig.changeType'] == 0]
        mods = [f["ID"] for f in changes if f['geogig.changeType'] == 1]

        adds_features = getFeaturesFromGeogigIds(adds, self.layer)
        mods_features = getFeaturesFromGeogigIds(mods, self.layer)


        for change in changes:
            if change["geogig.changeType"] == 0:
                fid = adds_features[change["ID"]].id()
                self.addedFeatures.append(fid)
            elif change["geogig.changeType"] == 1:
                fid = mods_features[change["ID"]].id()
                self.modifiedFeatures.append(fid)
            else:
                self.deletedFeatures.append(change["ID"])
        self.localChangesAvailable.emit(self.hasLocalChanges())

    def _gpkgPath(self):
        folder = pluginSetting("gpkgfolder") or os.path.join(os.path.expanduser('~'), 'geogig', 'repos')   
        subfolder = str(uuid.uuid4()).replace("-","")
        path = os.path.join(folder, self.user, self.repo, self.layername, subfolder)
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except:
                path = os.path.join(os.path.expanduser('~'), 'geogig', 'repos', self.user, 
                                    self.repo, self.layername, subfolder)
                if not os.path.exists(path):
                    os.makedirs(path)
        return os.path.join(path, self.layername + ".gpkg")

    #initial load of dataset
    def populate(self):
        if self.layer is None:
            self.backgroundingDownloader = BackgroundLayerDownload(self.server, self.user, self.repo,
                                                                    self.layername, self.commitid, extent=self.extent,
                                                                    filepath=self.gpkgPath)
            self.backgroundingDownloader.finished.connect(self.geopkgDownloaded)
            self.backgroundingDownloader.start()

    def geopkgDownloaded(self, layer,fname):
        self.layer = layer
        self.layername = layer.name()
        rect = self.layer.extent()
        self.extent = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]
        self.setupLayer()
        self.setMetadataInGpkg()
        setStyle(self)
        QgsProject.instance().addMapLayer(self.layer)
        hideGeogigidField(self.layer)
        self.layer.beforeRollBack.connect(self.beforeRollBack)
        self.layer.styleChanged.connect(self.styleChanged)

    def setMetadataInGpkg(self):
        setMetadataValue(self.gpkgPath, self.GEOGIG_URL, self.server.connector.url)
        setMetadataValue(self.gpkgPath, self.GEOGIG_USER, self.user)
        setMetadataValue(self.gpkgPath, self.GEOGIG_REPO, self.repo)
        setMetadataValue(self.gpkgPath, self.GEOGIG_LAYER, self.layername)
        setMetadataValue(self.gpkgPath, self.GEOGIG_COMMITID, self.commitid)
        setMetadataValue(self.gpkgPath, self.GEOGIG_EXTENT, str(self.extent))

    def _beforeEditing(self):
        pass

    def _beforeEditingStopped(self):
        self.loadChanges()

    def commitLocalChanges(self):
        self.editingStopped()

    # we just did a commit - there could be outstanding information on the server
    # a) get diff from base->HEAD (?)
    # b) revert to  base revision
    # c) apply diff
    #
    # this is to update the layer revision
    #
    # TODO: this will likely pull in changes outside of the bounds - we shouldn't do that
    def _afterCommitting(self):
        newCommitId = self.server.commitidForBranch(self.user, self.repo, "master")
        diff = self.server.diff(self.user, self.repo, self.layername,
                                newCommitId, self.commitid)
        revertToBaseRevision(self.gpkgPath, self.layername)
        applyDiff(self.gpkgPath, self.layername, diff)
        clearAuditTables(self.gpkgPath)

        self.commitid = newCommitId
        setMetadataValue(self.gpkgPath, self.GEOGIG_COMMITID, newCommitId)
        self.layer.setCustomProperty(self.GEOGIG_COMMITID, self.commitid)
        self.setupAbstract()
        self.layer.triggerRepaint()


class BackgroundLayerDownload(QObject):
    finished = pyqtSignal('PyQt_PyObject',str)

    def __init__(self, server, user, repo, layername, commitid, filepath, extent):
        QObject.__init__(self)
        self.server = server
        self.user = user
        self.repo = repo
        self.layername = layername
        self.commitid = commitid
        self.filepath = filepath
        self.extent = extent
        self.nfeaturesRead = 0
        self.actualLayerName = None

        # this puts the LayerGetter in its own thread
        self.worker = QThread()
        self.layer_getter = LayerGetter(server, user, repo, layername, commitid, filepath, extent)
        self.worker.started.connect(self.layer_getter.start)
        self.layer_getter.moveToThread(self.worker)
        self.layer_getter.completed.connect(self.completed)
        self.layer_getter.progress_occurred.connect(self.featuresRead)

    def start(self):
        startProgressBar("Downloading from GeoGig server", 0, currentWindow().messageBar())
        self.worker.start()  # start load

    # called (on main thread) when the work is done
    def completed(self):
        self.worker.quit()  # get rid of worker thread
        closeProgressBar()

        self.actualLayerName = self.layer_getter.actualLayerName
        layer = QgsVectorLayer(self.filepath+"|layername="+self.actualLayerName, self.actualLayerName)
        self.finished.emit(layer,self.filepath)

    # called as feature are read
    def featuresRead(self, nfeatsBatch):
        self.nfeaturesRead += nfeatsBatch
        setProgressText("Downloaded " + "{:,}".format(self.nfeaturesRead) + " features...")


class LayerGetter(QObject):
    # some data was loaded
    progress_occurred = pyqtSignal('int')
    completed = pyqtSignal()

    def __init__(self, server, user, repo, layername, commitid, filepath, extent):
        QObject.__init__(self)
        self.server = server
        self.user = user
        self.repo = repo
        self.layername = layername
        self.commitid = commitid
        self.filepath = filepath
        self.nFeaturesReported = 0
        self.layer = None
        self.extent = extent
        self.actualLayerName = None

    # do work of downloading
    def start(self):
        preExists = os.path.exists(self.filepath)
        query = QueryForLayerProto(self.server.connector, self.progressMade)
        query.query(self.user, self.repo, self.layername, self.commitid,
                                 filepath=self.filepath, extent=self.extent)
        if not preExists:
            self.actualLayerName = getDataTableName(self.filepath)
        else:
            self.actualLayerName = self.layername
        self.completed.emit()

    # periodically called - report to listener (other thread)
    def progressMade(self, nfeats):
        nreadBatch = nfeats - self.nFeaturesReported
        self.nFeaturesReported = nfeats
        self.progress_occurred.emit(nreadBatch)