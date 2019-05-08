import os
import sys
import threading
import struct
import traceback
import uuid
import time
from qgis.PyQt.QtCore import QTimer, Qt, QThread
from qgis.utils import iface
from qgis.core import QgsProject
import qgiscommons2.gui

from geogig.geogigwebapi.expression import ExpressionConverter
from geogig.layers.geogiglayer import *
from geogig.geogigwebapi.connector import GeogigError
from geogig.geopkgtools import *
from geogig.gui.fullreduceddialog import FullReducedDialog
from geogig.gui.constellationviewer import *
from geogig.protobuff.queryforlayerproto import QueryForLayerProto
from geogig.protobuff.querythread import QueryThread
from geogig.gui.progressbar import currentWindow
from geogig.protobuff.proto2qgis import FeatureWriter
from geogig.utils import GEOGIGID_FIELD, getFeatureFromGeogigId, hideGeogigidField
from geogig.styles import setStyle

class GeogigLiveLayer(GeogigLayer):

    def __init__(self, server, user, repo, layername, commitid, layer=None, extent=None, canvas=None):
        # import sys
        # sys.path.append('//Applications//PyCharm.app//Contents//debug-eggs//pycharm-debug.egg')
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        super().__init__(server, user, repo, layername, commitid, layer, extent)        
        self.canvas = canvas
        if layer is not None:
            v = layer.customProperty(GeogigLayer.GEOGIG_FULLDETAIL,'False')
            self.alwaysFullDetail = v.lower() == "true"
            self.screenmap_type = layer.customProperty(GeogigLayer.GEOGIG_SCREENMAP_TYPE, 'WithBBOX')
            self.screenmap_factor = float(layer.customProperty(GeogigLayer.GEOGIG_SCREENMAP_FACTOR, '1.0'))

        else:
            self.alwaysFullDetail = False # default
            self.screenmap_type = "WithBBOX"
            self.screenmap_factor = 1.0



        # user is currently editing, NOT saved to datastore (not saved to geogig)
        self._addedFeatures = []  # list of fid
        self._deletedFeatures = []  # list of [FID,GeogidID] (!)
        self._modifiedFeatures = []  # list of fid

        # track selection
        self.selected = []

        self.layerRefresher = GeoGigLiveLayerRefresher(self.server.connector, self,
                                                    fullDetail=self.alwaysFullDetail,
                                                    sm_factor=self.screenmap_factor,
                                                    sm_type=self.screenmap_type)
        # self.layerRefresher.setFullDetail(self.alwaysFullDetail)
        self.selectWatched = False
        try:
            if layer is not None:
                self.layer = layer                
                self.populate()
                self.loadChanges()
            else:                
                self.populate()            
        except:
            QgsMessageLog.logMessage(traceback.format_exc(), level=Qgis.Critical)
            self.valid = False

        self.selectWatched = True
        self.layer.selectionChanged.connect(self.selectionChanged)
        self.layer.beforeRollBack.connect(self.beforeRollBack)
        self.layer.styleChanged.connect(self.styleChanged)
        self.setupLayer()        
        self.layer.setTitle("GeoGig LIVE Layer")
        self.localChangesAvailable.emit(self.hasLocalChanges())
        self.layer.beforeEditingStarted.connect(self.beforeEditingStarted)
        if self.valid:
            self.refresh() # cause a background download of the data (populate only sets up layer)

    def _canvas(self):
        if self.canvas is not None:
            return self.canvas
        else:
            return iface.mapCanvas()

    def cleanup(self):
        super().cleanup()        
        iface.removeCustomActionForLayerType(self.changeOptimizationsAction)
        self.layerRefresher.cleanup()

    def _changesFile(self):
        path = QgsProject.instance().homePath()
        if path:
            return os.path.join(path, self.layer.id() + ".changes")
        else:
            return None

    def setupLayer(self):
        super().setupLayer()
        if self.layer is not None:
            self.changeOptimizationsAction = QAction("Change Data Optimizations...", iface)
            self.changeOptimizationsAction.triggered.connect(self.changeOptimizations)
            iface.addCustomActionForLayerType(self.changeOptimizationsAction, "GeoGig", QgsMapLayer.VectorLayer, False)
            iface.addCustomActionForLayer(self.changeOptimizationsAction , self.layer)

    def changeOptimizations(self):
        if self.layer.isEditable():
            QMessageBox.information(iface.mainWindow(), 'Cannot Data Optimization',
                                    "Please stop editing before changing the data Optimization.")
            return
        dlg = FullReducedDialog(self.alwaysFullDetail,self.screenmap_type,self.screenmap_factor)
        dlg.exec_()
        if dlg.ok:
            self.alwaysFullDetail = dlg.fullData

            self.layer.setCustomProperty(self.GEOGIG_FULLDETAIL, self.alwaysFullDetail)
            self.screenmap_type = dlg.sm_type
            self.layer.setCustomProperty(self.GEOGIG_SCREENMAP_TYPE, self.screenmap_type)
            self.screenmap_factor = dlg.sm_factor
            self.layer.setCustomProperty(self.GEOGIG_SCREENMAP_FACTOR, str(self.screenmap_factor))
            self.layerRefresher.sm_factor = self.screenmap_factor
            self.layerRefresher.sm_type = self.screenmap_type
            self.layerRefresher.setFullDetail(self.alwaysFullDetail)


    def selectionChanged(self, selected, deselected, clearAndSelect):
        self.selected = [f[GEOGIGID_FIELD] for f in self.layer.getFeatures(QgsFeatureRequest(selected))]

    def _buildFeatureFromShell(self, f):
        qfeat = QgsFeature()
        qfeat.setGeometry(f[0])
        qfeat.setAttributes(f[1])
        return qfeat

    def _buildFeatureFromShell2(self, f, feat):
        qfeat = QgsFeature(feat)
        qfeat.setGeometry(f[0])
        qfeat.setAttributes(f[1])
        return qfeat

    # dataset is {}.  geogigid -> (geometry,attributes) ("SHELL")
    def replaceLayer_complex(self,dataset,isEditing):
        if isEditing:
            self.disconnectEditSignals()
        else:
            self.layer.editingStarted.disconnect(self.editingStarted)
            self.layer.beforeEditingStarted.disconnect(self.beforeEditingStarted)
            self.layer.editingStopped.disconnect(self.editingStopped)
            self.layer.startEditing()

        fidsToPreserve = self.modifiedFeatures + self.addedFeatures + self._modifiedFeatures + self._addedFeatures
        geogigIdsToPreserve = [f[GEOGIGID_FIELD] for f in self.layer.getFeatures(QgsFeatureRequest(fidsToPreserve))]
        geogigIdsToPreserve = {id:id for id in self.deletedFeatures+self._deletedFeatures+geogigIdsToPreserve}

        toDelete = []
        ggid_fieldIndex = self.layer.fields().indexFromName(GEOGIGID_FIELD)
        for f in self.layer.getFeatures():
            attributes = f.attributes()  # get all of them now because we will likely need them
            gigid = attributes[ggid_fieldIndex]
            #gigid = f.attribute(ggid_fieldIndex)
            if gigid in geogigIdsToPreserve:
                continue # keep it unchanged
            newF = dataset.get(gigid)

            if not newF:
                toDelete.append(f.id())  # not in incomming dataset..
            elif not self.featuresEqual(attributes, f.geometry(), newF[1], newF[0]):
                # replace
                self.layer.updateFeature(self._buildFeatureFromShell2( newF,f))
                del dataset[gigid]  # mark as used
            else:
                del dataset[gigid]  # mark as used (no need to update)

        # need to go through the unused new ones, and see if they are in geogigIdsToPreserve
        toAdd = [self._buildFeatureFromShell(shell) for gid,shell in dataset.items() if gid not in geogigIdsToPreserve]  # un-used new ones
        self.layer.dataProvider().deleteFeatures(toDelete)
        self.layer.dataProvider().addFeatures(toAdd)
        if isEditing:
            self.connectEditingSignals()
        else:
            self.layer.commitChanges()
            self.layer.editingStarted.connect(self.editingStarted)
            self.layer.editingStopped.connect(self.editingStopped)
            self.layer.beforeEditingStarted.connect(self.beforeEditingStarted)

    # dataset is {}.  geogigid -> (geometry,attributes) ("SHELL")
    def replaceLayer_simple(self, dataset):
        self.disconnectEditSignals()

        toDelete = []
        ggid_fieldIndex = self.layer.fields().indexFromName(GEOGIGID_FIELD)
        # for each feature in the layer, see if in the incomming dataset
        for f in self.layer.getFeatures():
            attributes = f.attributes() # get all of them now because we will likely need them
            gigid = attributes[ggid_fieldIndex]
            #gigid = f.attribute(ggid_fieldIndex)
            # gigid = f[GEOGIGID_FIELD]
            newF = dataset.get(gigid)
            if not newF:
                toDelete.append(f.id())  # not in incomming dataset..
            elif not self.featuresEqual(attributes,f.geometry(), newF[1],newF[0]):
                # replace
                self.layer.updateFeature(self._buildFeatureFromShell2(newF,f))
                del dataset[gigid]  # mark as used
            else:
                del dataset[gigid]  # mark as used (no need to update)

        self.layer.dataProvider().deleteFeatures(toDelete)

        toAdd = [self._buildFeatureFromShell(f) for f in dataset.values()]  # un-used new ones
        self.layer.dataProvider().addFeatures(toAdd)
        self.connectEditingSignals()

    def featuresEqual(self,feature0_attributes, feature0_geom, feature1_attributes, feature1_geom):
        return feature0_attributes == feature1_attributes and feature0_geom.asWkb() == feature1_geom.asWkb()

    # this is called when a new dataset has been received and we want to replace the
    # current layer content with the data from here
    def newDatasetReceived(self, dataset):       
        if self.modifiedFeatures or self.addedFeatures or self.deletedFeatures or \
                self._modifiedFeatures or self._addedFeatures or self._deletedFeatures:
            # we have edits, so we have to do things the long way
            #features = [f for f in dataset.getFeatures()]
            features = dataset
            idx = self.layer.fields().indexOf(GEOGIGID_FIELD)
            idsToPreserve = self.modifiedFeatures + self.addedFeatures + self._modifiedFeatures + self._addedFeatures
            geogigIdsToPreserve = [f[idx] for f in self.layer.getFeatures(QgsFeatureRequest(idsToPreserve))]
            geogigIdsToPreserve.extend(self.deletedFeatures)
            geogigIdsToPreserve.extend(self._deletedFeatures)
            self.layer.dataProvider().deleteFeatures(
                [f.id() for f in self.layer.getFeatures() if f.id() not in idsToPreserve])
            toAdd = [f for f in features if f[idx] not in geogigIdsToPreserve]
            if toAdd:
                self.layer.dataProvider().addFeatures(toAdd)
        else:
            # no edits - do things the easy way
            self.layer.dataProvider().truncate()
            self.layer.dataProvider().addFeatures(dataset)

        if self.selected:
            selected = []
            for fid in self.selected:
                feature = self.getFeatureFromGeogigId(fid)
                if feature is not None:
                    selected.append(feature.id())

            if self.selectWatched:
                self.layer.selectionChanged.disconnect(self.selectionChanged)
                self.layer.dataProvider().dataChanged.emit()  # for attribute table -- make it aware of a datachanges. this must be followed by a selection changed ...
                self.layer.selectByIds(selected)
                self.layer.selectionChanged.connect(self.selectionChanged)
            else:
                self.layer.dataProvider().dataChanged.emit()  # for attribute table -- make it aware of a datachanges. this must be followed by a selection changed ...
                self.layer.selectByIds(selected)
        else:
            if self.selectWatched:
                self.layer.selectionChanged.disconnect(self.selectionChanged)
                self.layer.dataProvider().dataChanged.emit()  # for attribute table -- make it aware of a datachanges. this must be followed by a selection changed ...
                self.layer.selectByIds([])
                self.layer.selectionChanged.connect(self.selectionChanged)
            else:
                self.layer.dataProvider().dataChanged.emit()  # for attribute table -- make it aware of a datachanges. this must be followed by a selection changed ...
                self.layer.selectByIds([])

        rect = self._canvas().extent()
        rect = self.extentToLayerCrs(rect)
        self.extent = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]
        self.layer.setCustomProperty(self.GEOGIG_EXTENT, self.extent)
        iface.mapCanvas().clearCache()
        self.layer.triggerRepaint()

    def resetBufferChanges(self):
        self._deletedFeatures = []
        self._modifiedFeatures = []
        self._addedFeatures = []

    def beforeRollBack(self):
        self.resetBufferChanges()
        self.rolledback = True

    def disconnectEditSignals(self):
        self.layer.attributeValueChanged.disconnect(self._attributeChanged)
        self.layer.featureAdded.disconnect(self._featureAdded)
        self.layer.featureDeleted.disconnect(self._featureDeleted)
        self.layer.geometryChanged.disconnect(self._geometryChanged)

    def _attributeChanged(self, featureid, fieldidx, value):
        if featureid >= 0:
            self._modifiedFeatures.append(featureid)

    def _featureAdded(self, featureid):
        if featureid >= 0:
            self._addedFeatures.append(featureid)

    def _featureDeleted(self, featureid):
        if featureid >= 0:
            features = [f for f in self.layer.dataProvider().getFeatures(QgsFeatureRequest(featureid))]
            if features:
                gid = features[0][GEOGIGID_FIELD]
                self._deletedFeatures.append([featureid, gid])

    def _geometryChanged(self, featureid, geom):
        self._attributeChanged(featureid,None,None)

    def featureChanged(self, featureid):
        if featureid >= 0:
            # don't record a modification if it was added - it will be handled by add
            # don't re-record modifications
            if featureid not in self.addedFeatures and featureid not in self.modifiedFeatures:
                self.modifiedFeatures.append(featureid)

    def featureAdded(self, featureid):
        if featureid >= 0:
            self.addedFeatures.append(featureid)

    def featureDeleted(self, fid_gid):
        featureid = fid_gid[0]
        gigid = fid_gid[1]
        if featureid >= 0:
            # if you delete a feature, don't record it's add or modification
            inAdded = featureid in self.addedFeatures
            self.modifiedFeatures = difference(self.modifiedFeatures, [featureid])
            self.addedFeatures = difference(self.addedFeatures, [featureid])
            if not inAdded:  # no need to do anything if it was add (just don't add it)
                self.deletedFeatures.append(gigid)

    def addBufferChanges(self):
        for fid in self._modifiedFeatures:
            self.featureChanged(fid)
        for fid in self._addedFeatures:
            self.featureAdded(fid)
        for fid_gid in self._deletedFeatures:
            self.featureDeleted(fid_gid)
        self.resetBufferChanges()

    # changes file is;
    #    <number of deleted features -- INT>
    #    <len of deleted feature 1's ID -- INT>
    #    <feature 1's GeogigID -- unicode>
    #    ....
    #    <number of features modified -- INT>
    #    <if there are modified features, then protobuf of the features -- binary protobuf>
    #    <number of features inserted --INT>
    #    <if there are inserted features, then protobuf of the features -- binary protobuf>
    def saveChanges(self):
        changesFile = self._changesFile()
        if changesFile is None:
            if self.hasLocalChanges():
                raise GeogigError("Cannot save local changes. Project must be saved first.")
            else:
                return
        deletedGigIds = self.deletedFeatures
        modifiedFeatures = list(self.layer.getFeatures(self.modifiedFeatures))
        addedFeatures = list(self.layer.getFeatures(self.addedFeatures))

        if self.hasLocalChanges():
            with open(changesFile, "wb") as f:
                f.write(struct.pack('i', len(deletedGigIds)))  # write int - # of deleted
                for gigid in deletedGigIds:
                    s = gigid.encode()
                    f.write(struct.pack('i', len(s)))  #len
                    f.write(s)
                f.write(struct.pack('i', len(modifiedFeatures)))  # write int - # of mod
                if len(modifiedFeatures) >0:
                    writer = FeatureWriter(modifiedFeatures)
                    f.write(writer.asBytes())
                    f.write(bytes([0])) # separator
                f.write(struct.pack('i', len(addedFeatures)))  # write int - # of mod
                if len(addedFeatures) > 0:
                    writer = FeatureWriter(addedFeatures)
                    f.write(writer.asBytes())
        elif os.path.exists(changesFile):
                os.remove(changesFile)

    def loadChanges(self):
        changesFile = self._changesFile()
        if os.path.exists(changesFile):
            _ft = None
            with open(changesFile,"rb") as f:
                query = QueryForLayerProto(None)
                ndeletes = struct.unpack('i', f.read(4))[0]
                deletedFeatureGigIDs = []
                for i in range(0,ndeletes):
                    len  = struct.unpack('i', f.read(4))[0]
                    data = f.read(len)
                    id = data.decode()
                    deletedFeatureGigIDs.append(id)
                nModified = struct.unpack('i', f.read(4))[0]
                modifiedFeatures = []
                if nModified>0:
                    _ft,modifiedFeatures = query.readFromStream(f)
                    modifiedFeatures= list(modifiedFeatures)
                nAdded= struct.unpack('i', f.read(4))[0]
                addedFeatures = []
                if nAdded > 0:
                    _ft,addedFeatures = query.readFromStream(f)
                addedFeatures= list(addedFeatures)

            if _ft is not None:
                fields = _ft.getFields()

            #process
            self.deletedFeatures = deletedFeatureGigIDs
            deletedFeats = [self.getFeatureFromGeogigId(gid) for gid in self.deletedFeatures]
            deletedIds = [f.id() for f in deletedFeats if f is not None]
            self.layer.deleteFeatures(deletedIds)

            self.modifiedFeatures = []
            for feature in modifiedFeatures:
                feature.setFields(fields,initAttributes=False)
                previousFeature = self.getFeatureFromGeogigId(feature[GEOGIGID_FIELD])
                if previousFeature is not None:
                    self.layer.dataProvider().deleteFeatures([previousFeature.id()])
                self.layer.dataProvider().addFeatures([feature])
                self.modifiedFeatures.append(self.getFeatureFromGeogigId(feature[GEOGIGID_FIELD]).id())

            self.addedFeatures = []
            for feature in addedFeatures:
                feature.setFields(fields,initAttributes=False)
                self.layer.dataProvider().addFeatures([feature])
                self.addedFeatures.append(self.getFeatureFromGeogigId(feature[GEOGIGID_FIELD]).id())

            self.layer.triggerRepaint()
        
    # returns a list of
    # {
    #  'ID':<geogig ID - string>,
    #  'geogig.changeType':  - int 0=add,1=modify,2=delete,
    #  'old': <QgsFeature> -- old feature (None if add)
    #  'new': <QgsFeature> -- new feature (None if delete)
    # }
    def getLocalChangeset(self):
        deleted_geogigids  = self.deletedFeatures
        modified_geogigids = [f[GEOGIGID_FIELD] for f in self.layer.getFeatures(QgsFeatureRequest(self.modifiedFeatures))]

        geogigids = deleted_geogigids + modified_geogigids

        queryForLayerProto = QueryForLayerProto(self.server.connector)
        query = QueryForLayerProto.createQueryFIDs(self.commitid,geogigids)
        url = QueryForLayerProto.createURL(self.server.connector,
                                           self.user,self.repo,self.layername)
        memLayer = queryForLayerProto.querySimple(url,query)

        result =[]
        for fid in self.addedFeatures:
            f = list(self.layer.getFeatures(QgsFeatureRequest([fid])))[0]
            item = {'ID':f[GEOGIGID_FIELD],
                     'geogig.changeType':0,
                    'old':None,
                    'new':f}
            result.append(item)

        for gigid in deleted_geogigids:
            f = getFeatureFromGeogigId(gigid, memLayer)
            item = {'ID': f[GEOGIGID_FIELD],
                    'geogig.changeType': 2,
                    'old': f,
                    'new': None}
            result.append(item)

        for gigid in modified_geogigids:
            f = getFeatureFromGeogigId(gigid, memLayer)
            ff= self.getFeatureFromGeogigId(gigid)
            item = {'ID': f[GEOGIGID_FIELD],
                    'geogig.changeType': 1,
                    'old': f,
                    'new': ff}
            result.append(item)

        return result

    def revertChanges(self):
        self.modifiedFeatures = []
        self.deletedFeatures = []
        self.addedFeatures = []
        self.refresh()  # data needs to be re-downloaded
        self.layer.triggerRepaint()
        self.localChangesAvailable.emit(self.hasLocalChanges())
        self.saveChanges()

    def showChanges(self):
        if not self.hasLocalChanges():
            iface.messageBar().pushMessage("", "The layer has no local changes", level=Qgis.Info, duration=5)
            return
        changes = {self.layername: self.getLocalChangeset()}
        dialog = DiffViewerDialog(changes)
        dialog.exec_()

    def refresh(self, forceRefresh = True):
        if self.valid:
            self.layerRefresher.refresh(forceRefresh = forceRefresh)        

    #initial load of dataset -- creates the schema and base memory layer
    def populate(self):
        bounds = self.server.layerExtent(self.user, self.repo, self.layername, self.commitid)
        if self.extent is not None:
            extentRect = QgsRectangle(*self.extent)
        else:
            extentRect = self._canvas().extent()
            extentRect = self.extentToLayerCrs(extentRect)
        extent = [extentRect.xMinimum(), extentRect.yMinimum(), extentRect.xMaximum(), extentRect.yMaximum()]
        if extent[0] == extent[3]: #project is not initialized and canvas has no extent. We use the full layer extent
            extent = bounds
        layer = self.server.getLayer(self.user, self.repo, self.layername, self.commitid,
                     extent, iface.mainWindow().width(), iface.mainWindow().height(), limit=1)
        if self.layer is None:
            self.layer = layer
            setStyle(self)
            QgsProject.instance().addMapLayer(self.layer, self.canvas is None) 
            self.extent = extent
        else:
            '''This is to fix an issue with memory layer having wrong field names when stored in a QGIS project'''
            #need to replace the fields and truncate
            self.layer.dataProvider().truncate()
            self.layer.dataProvider().deleteAttributes(list(range(0,len(self.layer.fields()))))
            self.layer.updateFields()
            # add fields back in (these will be properly named and typed)
            self.layer.dataProvider().addAttributes(layer.fields())
            self.layer.updateFields()
            features = [f for f in self.layer.getFeatures()]
            self.newDatasetReceived(features)  # will set everything up for us
        self.layer.setExtent(QgsRectangle(*bounds))
        hideGeogigidField(self.layer)
        self.valid = True

    def connectEditingSignals(self):
        self.layer.attributeValueChanged.connect(self._attributeChanged)
        self.layer.featureAdded.connect(self._featureAdded)
        self.layer.featureDeleted.connect(self._featureDeleted)
        self.layer.geometryChanged.connect(self._geometryChanged)

    def beforeEditingStarted(self):
        if not self.layerRefresher.getFullDetail():
            # need to clean out the features in the layer - or we'll get phantom edits when we switch it up
            areMods = self.modifiedFeatures or self.addedFeatures or self.deletedFeatures or \
                self._modifiedFeatures or self._addedFeatures or self._deletedFeatures
            if not areMods:
                #simple case - can just truncate the layer
                self.layer.dataProvider().truncate()
            else:
                fidsToPreserve = self.modifiedFeatures + self.addedFeatures + self._modifiedFeatures + self._addedFeatures
                geogigIdsToPreserve = [f[GEOGIGID_FIELD] for f in
                                       self.layer.getFeatures(QgsFeatureRequest(fidsToPreserve))]
                geogigIdsToPreserve = {id: id for id in
                                       self.deletedFeatures + self._deletedFeatures + geogigIdsToPreserve}
                toDeleteFids = []
                ggid_fieldIndex = self.layer.fields().indexFromName(GEOGIGID_FIELD)
                for f in self.layer.getFeatures():
                    gigid = f.attribute(ggid_fieldIndex)
                    if gigid not in geogigIdsToPreserve:
                        toDeleteFids.append(f.id())
                self.layer.dataProvider().deleteFeatures(toDeleteFids)


    def _beforeEditing(self):
        self.connectEditingSignals()
        if not self.layerRefresher.getFullDetail():
            QMessageBox.information(iface.mainWindow(), "Layer update",
                                                            'You are currently seeing a reduced and simplified version of the layer.\n'
                                                            'Before starting editing, the layer has to be updated.\n'
                                                            'This might take some time to complete\n')
            self.layerRefresher.setFullDetail(True)

    def commitLocalChanges(self):
        self.connectEditingSignals() # required for editingStopped
        self.editingStopped()


    def _beforeEditingStopped(self):
        self.addBufferChanges()
        self.disconnectEditSignals()
        self.layerRefresher.setFullDetail(self.alwaysFullDetail, refresh = False)

    def _afterCommitting(self):
        if self.commitid != "HEAD":
            self.commitid = self.server.commitidForBranch(self.user, self.repo, "master")
            self.layer.setCustomProperty(self.GEOGIG_COMMITID, self.commitid)
        self.refresh()


class GeoGigLiveLayerRefresher(object):

    nProgressBarsOpen = 0
    nfeaturesRead = 0
    lock = threading.RLock() # this might not be necessary - I think this will always be happening on the same ui thread

    def __init__(self, connector, geogiglayer, fullDetail=False,sm_factor=1.0,sm_type="WithBBOX"):
        self.connector = connector
        self.geogiglayer = geogiglayer

        self.queryThread = QueryThread(self.connector)
        self.queryThread.started.connect(self.datasetStart)
        self.queryThread.finished.connect(self.datasetReceived)
        self.queryThread.progress_occurred.connect(self.featuresRead)

        self.refreshTimer = QTimer()
        self.refreshTimer.setSingleShot(True)
        self.refreshTimer.timeout.connect(self.makeQuery)

        self.lastExtent = None
        self.sm_factor = sm_factor
        self.sm_type = sm_type

        root = QgsProject.instance().layerTreeRoot()
        root.visibilityChanged.connect(self.visibilityChanged) # track all layer visibility changes
        self.fullDetail = fullDetail
        #root.addedChildren.connect(self.layerTreeAddedTo) # track when layer is added to tree

    # called when layer is removed
    def cleanup(self):
        # don't track this anymore (it causes a problem because the c++ object is
        # deleted, but the python object isn't)
        root = QgsProject.instance().layerTreeRoot()
        root.visibilityChanged.disconnect(self.visibilityChanged)

    def isLayerVisible(self):
        if self.geogiglayer.layer is None:
            return None
        layerId = self.geogiglayer.layer.id()
        if self.geogiglayer.canvas is None:
            treelayer = QgsProject.instance().layerTreeRoot().findLayer(layerId) # QgsLayerTreeLayer
            if treelayer is None:
                return False
            if not treelayer.isVisible():
                return False # definitely not visible
        # likely visible, do a simple scale-range check
        return self.geogiglayer.layer.isInScaleRange(self.geogiglayer._canvas().scale())

    def visibilityChanged(self, qgsLayerTreeNode):
        if self.isLayerVisible():
            self.refresh(forceRefresh = False, tryToRepopulate = True)

    def openProgress(self):
        with self.lock:
            if self.nProgressBarsOpen == 0:
                self.nfeaturesRead = 0
                qgiscommons2.gui.startProgressBar("Transferring data from GeoGig", 0, currentWindow().messageBar())
            self.nProgressBarsOpen += 1

    def closeProgress(self):
        with self.lock:
            self.nProgressBarsOpen -= 1
            if self.nProgressBarsOpen == 0:
                qgiscommons2.gui.closeProgressBar()

    # sometimes the progress bar can be closed by another thread/function
    #  this will re-open it if that happens.
    # ex. when you have a layers being populated() during a refresh()
    #     which can occur on project load
    def ensureProgressOpen(self):
        _progressActive = qgiscommons2.gui._progressActive
        if _progressActive:
            return  # nothing to do
        qgiscommons2.gui.startProgressBar("Transferring data from GeoGig", 0, currentWindow().messageBar())

    # called by backgrounding feature loader (self.queryThread)
    # this is for progress indication
    def featuresRead(self, nfeatsBatch):
        with self.lock:
            self.ensureProgressOpen()
            self.nfeaturesRead += nfeatsBatch
            try:
                qgiscommons2.gui.setProgressText("Read " + "{:,}".format(self.nfeaturesRead) + " features...")
            except:
                pass # could be a problem...

    # occurs when extents change, call this from geogiglayer
    def refresh(self, forceRefresh = True, tryToRepopulate = False):
        if tryToRepopulate and not self.geogiglayer.valid:
            try:
                self.geogiglayer.populate()
            except:
                item = QgsProject.instance().layerTreeRoot().findLayer(self.geogiglayer.layer.id())
                item.setItemVisibilityCheckedRecursive(False)
                return 
        if not forceRefresh:
            extentRect = self.geogiglayer.extentToLayerCrs(self.geogiglayer._canvas().extent())
            extent = [extentRect.xMinimum(), extentRect.yMinimum(), extentRect.xMaximum(), extentRect.yMaximum()]
            if self.lastExtent == extent:
                return
        # set time -- will fire after 100ms and call makeQuery
        if self.refreshTimer.isActive():
            self.refreshTimer.setInterval(100)  # restart
        else:
            self.refreshTimer.start(100)

    #downloads the current extent at full detail. Called when entering or exiting the editing mode.
    def setFullDetail(self, fullDetail, refresh = True):
        self.fullDetail = fullDetail
        if refresh:
            self.makeQuery()

    def getFullDetail(self):
        return self.fullDetail

    # thread has started to do work
    def datasetStart(self,url,query):
        self.timeStart = time.perf_counter()
        QgsMessageLog.logMessage("loading dataset url={}, query={}".format(url,str(query)))


    # return true if you shouldn't draw this layer
    #   if its rules-based, and all the rules depend on scale, and all the rules are "out-of-scale"
    def doNotDrawScale(self,r,scale):
        if not isinstance(r,QgsRuleBasedRenderer):
            return False
        # any of them are NOT scale dependent, then need to draw
        if any([not r.dependsOnScale() for r in r.rootRule().children()]):
            return False
        return not any([r.isScaleOK(scale) for r in r.rootRule().children()])


    def ecqlFromLayerStyle(self):
        canvas = self.geogiglayer._canvas()
        ms = canvas.mapSettings()
        ctx = QgsRenderContext.fromMapSettings(ms)

        r = self.geogiglayer.layer.renderer().clone()
        try:
            r.startRender(ctx, self.geogiglayer.layer.fields())
            if self.doNotDrawScale(r,canvas.scale()):
                return "EXCLUDE"
            expression = r.filter()
            if expression == "" or expression == "TRUE":
                return None
            converter = ExpressionConverter(expression)
            return converter.asECQL()
        except:
            return None
        finally:
            r.stopRender(ctx)


    def makeQuery(self):
        self.queryThread.abort()
        self.queryThread.wait()  # wait for it to abort
        if not self.isLayerVisible():
            return # don't do anything if the layer is invisible NOTE: layer likely has data in it
        self.openProgress()
        extent = self.geogiglayer.extentToLayerCrs(self.geogiglayer._canvas().extent())
        self.lastExtent = [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()]
        self.queryThread.createURL(self.geogiglayer.user, self.geogiglayer.repo, self.geogiglayer.layername)
        if self.fullDetail:
            self.queryThread.createQuery(self.geogiglayer.commitid,
                                      self.lastExtent,
                                      simplifyGeom = False,
                                      ecqlFilter = self.ecqlFromLayerStyle())
        else:
            self.queryThread.createQuery(self.geogiglayer.commitid,
                                      self.lastExtent,
                                      self.geogiglayer._canvas().width(),
                                      self.geogiglayer._canvas().height(),
                                      screenMap_factor=self.sm_factor,
                                      screenMap_type=self.sm_type,
                                      ecqlFilter = self.ecqlFromLayerStyle())
        self.queryThread.start()


    # called  by backgrounding feature loader (self.queryThread)
    # this is after the dataset has loaded.
    # None -> aborted
    def datasetReceived(self, memorydataset):
        if memorydataset is not None:
            end_time = time.perf_counter()
            QgsMessageLog.logMessage(
                "Dataset received ({}) - {:,} features in {}s"
                    .format(self.geogiglayer.layername,len(memorydataset),end_time - self.timeStart))
        self.closeProgress()
        if memorydataset is None:
            return
        try:
            self.geogiglayer.newDatasetReceived(memorydataset)
        except Exception as e:
            QgsMessageLog.logMessage("error - "+str(e))