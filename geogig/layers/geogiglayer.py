import struct
import traceback
import uuid

from qgiscommons2.gui import execute, startProgressBar

from geogig.conflicts import *
from geogig.crs import xform
from geogig.geogigwebapi.connector import GeogigAuthException, GeogigError
from geogig.geogigwebapi.server import Server
from geogig.geopkgtools import *
#from geogig.gui.fullreduceddialog import FullReducedDialog
from geogig.gui.commitdialog import CommitDialog
from geogig.gui.constellationviewer import *
from geogig.gui.diffviewer import DiffViewerDialog
from geogig.protobuff.queryforlayerproto import QueryForLayerProto
from geogig.protobuff.proto2qgis import FeatureWriter
from geogig.utils import GEOGIGID_FIELD, hideGeogigidField
from geogig.styles import saveStyle
from qgis.core import Qgis
from qgis.utils import iface

class GeogigLayer(QObject):

    GEOGIG_URL = "GEOGIG_URL"
    GEOGIG_USER = "GEOGIG_USER"
    GEOGIG_REPO = "GEOGIG_REPO"
    GEOGIG_LAYER = "GEOGIG_LAYER"
    GEOGIG_COMMITID = "GEOGIG_COMMITID"
    GEOGIG_LAYERCLASS = "GEOGIG_LAYERCLASS"
    GEOGIG_EXTENT = "GEOGIG_EXTENT"
    GEOGIG_FULLDETAIL = "GEOGIG_FULLDETAIL"
    GEOGIG_SCREENMAP_TYPE = "GEOGIG_SCREENMAP_TYPE"
    GEOGIG_SCREENMAP_FACTOR = "1.0"

    localChangesAvailable = pyqtSignal('bool')

    def __init__(self, server, user, repo, layername, commitid, layer=None, extent=None):
        QObject.__init__(self)
        self.server = server
        self.user = user
        self.repo = repo
        self.layername = layername
        self.commitid = commitid
        self.layer = None
        self.commiting = False
        self.branch = "master"
        self.extent = extent #extent is stored in layer CRS
        self.layerCrs = None
        self.valid = False

        # saved to datastore, but not saved to geogig
        self.addedFeatures = [] # list of fid
        self.deletedFeatures = [] # list of GeogidID
        self.modifiedFeatures = [] # list of fid

        self.localChangesAvailable.connect(self.setupAbstract)  
        self.rolledback = False

    def isValid(self):
        return self.valid

    def cleanup(self):
        iface.removeCustomActionForLayerType(self.constellationAction)
        iface.removeCustomActionForLayerType(self.revertChangesAction)
        iface.removeCustomActionForLayerType(self.showChangesAction)
        iface.removeCustomActionForLayerType(self.commitLocalChangesAction)
        iface.removeCustomActionForLayerType(self.saveStyleAction)

    def setupAbstract(self):
        abstract = "CommitID:" + str(self.commitid) +"\n"
        abstract += "User: "+self.user+"\n"
        abstract += "Repository: "+ self.repo+"\n"
        localChanges = "No Local Changes\n"
        if self.hasLocalChanges():
            localChanges = "{} features modified, {} added, {} deleted\n".format(len(self.modifiedFeatures),
                                                                               len(self.addedFeatures),
                                                                               len(self.deletedFeatures))
        abstract += localChanges
        self.layer.setAbstract(abstract)

    def showConstellation(self):
        dlg = ConstellationViewerDialog(self.server, self.user, self.repo)
        dlg.show()
        dlg.exec_()

    def setCustomProperties(self):
        self.layer.setCustomProperty(self.GEOGIG_FULLDETAIL, self.alwaysFullDetail)
        self.layer.setCustomProperty(self.GEOGIG_URL, self.server.connector.url)
        self.layer.setCustomProperty(self.GEOGIG_USER, self.user)
        self.layer.setCustomProperty(self.GEOGIG_REPO, self.repo)
        self.layer.setCustomProperty(self.GEOGIG_LAYER, self.layername)
        self.layer.setCustomProperty(self.GEOGIG_COMMITID, self.commitid)
        self.layer.setCustomProperty(self.GEOGIG_LAYERCLASS, self.__class__.__name__)
        self.layer.setCustomProperty(self.GEOGIG_EXTENT, self.extent)

        self.layer.setCustomProperty(self.GEOGIG_SCREENMAP_TYPE, self.screenmap_type)
        self.layer.setCustomProperty(self.GEOGIG_SCREENMAP_FACTOR, str(self.screenmap_factor))

    def styleChanged(self):
        self.setCustomProperties()
        hideGeogigidField(self.layer)

    def setupLayer(self):
        if self.layer is not None:
            self.setCustomProperties()    
            self.layer.editingStarted.connect(self.editingStarted)
            self.layer.editingStopped.connect(self.editingStopped)

            self.constellationAction = QAction("Show Repo Constellation...", iface)
            self.constellationAction.triggered.connect(self.showConstellation)

            iface.addCustomActionForLayerType(self.constellationAction, "GeoGig", QgsMapLayer.VectorLayer, False)
            iface.addCustomActionForLayer(self.constellationAction, self.layer)

            self.revertChangesAction = QAction("Revert Local Changes", iface)
            self.revertChangesAction.triggered.connect(self.revertChanges)
            self.localChangesAvailable.connect(self.revertChangesAction.setEnabled)
            iface.addCustomActionForLayerType(self.revertChangesAction, "GeoGig", QgsMapLayer.VectorLayer, False)
            iface.addCustomActionForLayer(self.revertChangesAction, self.layer)

            self.showChangesAction = QAction("Show Local Changes...", iface)
            self.showChangesAction.triggered.connect(self.showChanges)
            self.localChangesAvailable.connect(self.showChangesAction.setEnabled)
            iface.addCustomActionForLayerType(self.showChangesAction, "GeoGig", QgsMapLayer.VectorLayer, False)
            iface.addCustomActionForLayer(self.showChangesAction, self.layer)

            self.commitLocalChangesAction = QAction("Commit Local Changes...", iface)
            self.commitLocalChangesAction.triggered.connect(self.commitLocalChanges)
            self.localChangesAvailable.connect(self.commitLocalChangesAction.setEnabled)
            iface.addCustomActionForLayerType(self.commitLocalChangesAction, "GeoGig", QgsMapLayer.VectorLayer, False)
            iface.addCustomActionForLayer(self.commitLocalChangesAction, self.layer)

            self.saveStyleAction = QAction("Save Layer Style as Default Style...", iface)
            self.saveStyleAction.triggered.connect(self.saveStyle) 
            iface.addCustomActionForLayerType(self.saveStyleAction, "GeoGig", QgsMapLayer.VectorLayer, False)
            iface.addCustomActionForLayer(self.saveStyleAction, self.layer)

            self.localChangesAvailable.emit(self.hasLocalChanges())

    def resetChanges(self):
        self.deletedFeatures = []
        self.modifiedFeatures = []
        self.addedFeatures = []

    def saveStyle(self):
        saveStyle(self)
        iface.messageBar().pushMessage("", "Style correctly saved", level=Qgis.Info, duration=5)

    def extentToLayerCrs(self, extent):
        projectCrs = QgsProject.instance().crs()
        if self.layerCrs is None:
            self.layerCrs = self.server.layerCrs(self.user, self.repo, self.layername, self.commitid)
        return xform(extent, projectCrs, self.layerCrs)

    def editingStarted(self):
        self.rolledback = False
        if not self.commiting:
            self._beforeEditing()
            self.commiting = True

    def _beforeEditingStopped(self):
        pass

    def resetBufferChanges(self):
        pass

    def editingStopped(self):
        try:
            if self.rolledback:
                self.resetBufferChanges()
            self._beforeEditingStopped()
            if self.hasLocalChanges():
                QApplication.restoreOverrideCursor()
                try:
                    self.checkCanCommit()
                    dlg = CommitDialog()
                    dlg.exec_()
                    if dlg.message is not None:
                        text = dlg.message or "Changes"
                        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
                        self.server.commitChanges(self, text)
                        self._afterCommitting()
                        self.resetChanges()
                    else:
                        iface.messageBar().pushMessage("Commit", "Features were not commited to the repo. They will be kept in the Geogig edit buffer", level=Qgis.Info, duration=5)
                except Exception as e:
                    iface.messageBar().pushMessage("Commit", str(e), level=Qgis.Warning, duration=10)
                finally:
                    self.saveChanges()
            else:
                self.saveChanges()
        finally:
            QApplication.restoreOverrideCursor()
            self.commiting = False
            self.localChangesAvailable.emit(self.hasLocalChanges())
            self.layer.dataProvider().dataChanged.emit()


    def checkCanCommit(self):
        if self.server.connector.user != self.user:
            raise GeogigError("You logged in with a different user. Features were not commited and will be kept in the Geogig edit buffer")
        try:
            headid = self.server.commitidForBranch(self.user, self.repo, "master")
        except GeogigAuthException:
            raise GeogigError("You are not logged in. Features were not commited and will be kept in the Geogig edit buffer")
        except GeogigError:
            raise GeogigError("Cannot connect to server. Features were not commited and will be kept in the Geogig edit buffer")
        if self.commitid=="HEAD":
            return # by definition, up to date
        if headid != self.commitid:
            filteredIds = [f[GEOGIGID_FIELD] for f in self.layer.getFeatures(QgsFeatureRequest(self.modifiedFeatures))]
            filteredIds.extend(self.deletedFeatures)
            featureFilter = {"featureIds": filteredIds}
            diff = self.server.diff(self.user, self.repo, self.layername,
                             headid, self.commitid, featureFilter)
            if diff:
                conflicts = solveConflicts(self, diff)
                if not conflicts:
                    raise GeogigError("Conflicts were not solved. Features were not commited to the repo.")

    def getFeatureFromGeogigId(self, fid):
        return getFeatureFromGeogigId(fid, self.layer)

    def hasLocalChanges(self):
        return len(self.modifiedFeatures)>0 or \
               len(self.deletedFeatures)>0 or \
               len(self.addedFeatures)>0
