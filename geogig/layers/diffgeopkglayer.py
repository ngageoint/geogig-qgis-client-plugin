import os
import uuid
import sip
import shutil
from itertools import islice, chain

from qgis.PyQt.QtCore import QVariant
from qgis.core import (QgsVectorFileWriter, QgsCoordinateReferenceSystem, QgsFields, QgsField, QgsFeature,
                        QgsApplication, QgsProject, QgsVectorLayer, QgsWkbTypes, edit)

from geogig.geogigwebapi.server import Server
from geogig.protobuff.featuretype import FeatureTypeHelper
from geogig.geopkgtools import getDataTableName

from qgiscommons2.settings import pluginSetting


# note - Python binding for QgsVectorFileWriter don't allow you to
# control the layer name, so you cannot use it to write multiple layers into
# a single geopkg.  We want to stream features to the geopkg.
# Therefore, we do this in two steps;
#   a) create a memory datastore for each layer
#   b) use the QgsVectorFileWriter to create each layer
#   c) Destroy all the QgsVectorFileWriter objects to close the file
#   D) stream the features, and use a normal QgsVectorLayer to write the features
#
# Yes, a lot of work just because the python bindings are missing
class DiffGeoPKGMultiLayer:
    resourcesPath = os.path.join(os.path.dirname(__file__),"..", "resources")
    ptStyle = os.path.join(resourcesPath, "difflayer_points.qml")
    lineStyle = os.path.join(resourcesPath, "difflayer_lines.qml")
    polyStyle = os.path.join(resourcesPath, "difflayer_polygons.qml")
    diffStyles = [ptStyle, lineStyle, polyStyle]  # as per layer.geometryType()

    def __init__(self, server, user, repo, commitA, commitB, layer=None, commitAUser=None, commitARepo=None):
        self.server = server
        self.user = user
        self.repo = repo
        self.commitA = commitA
        self.commitB = commitB
        self.commitARepo = commitARepo
        self.commitAUser = commitAUser
        self.fname = self._gpkgPath()
        # layers for this diff
        if layer is None:
            layers0 = set(self.server.layers(self.user, self.repo, commitA))
            layers1 = set(self.server.layers(self.user, self.repo, commitB))
            self.layers = layers0.union(layers1)
        else:
            self.layers = [layer]

    def _gpkgPath(self):
        folder = pluginSetting("difffolder") or os.path.join(os.path.expanduser('~'), 'geogig', 'diff')   
        filename = str(uuid.uuid4()).replace("-","")
        path = os.path.join(folder, self.user, self.repo)
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except:
                path = os.path.join(os.path.expanduser('~'), 'geogig', 'diff', self.user, self.repo)
                if not os.path.exists(path):
                    os.makedirs(path)
        return os.path.join(path, filename + ".gpkg")

    def addToProject(self):
        addedLayers=[]
        self.write()
        for layerName in self.layers:
            uri = self.fname + "|layername=" + layerName
            layer = QgsVectorLayer(uri)
            if layer.featureCount() >0: # don't bother with 0 feature layers...
                layer.setName("DIFF - " + layerName)
                layer.setTitle("GeoGig Diff Layer - " + layerName)

                layer.setAbstract(self.createAbstract(layerName))
                self.setStyle(layer)
                QgsProject.instance().addMapLayer(layer)
                addedLayers.append(layer)
        return addedLayers

    def createAbstract(self, layerName):
        return "user: {}\nrepo: {}\ncommit A: {}\ncommit B: {}".format(
            self.user, self.repo, self.commitA, self.commitB
        )

    def setStyle(self, layer):
        type = layer.geometryType()
        style = DiffGeoPKGMultiLayer.diffStyles[type]
        layer.loadNamedStyle(style)


    def getDiff(self,layerName):
        return self.server.diff(self.user, self.repo, layerName,
                         self.commitA,
                         self.commitB,
                         returnAsIterator=True,
                         oldRefUser=self.commitAUser, oldRefRepoName=self.commitARepo
                                )

    def write(self):
         for layer in self.layers:
            ftHelper, featureIterator = self.getDiff(layer)
            memory = self.createMemoryDS(ftHelper,layer)
            # layerInfo[layer] = {"name":layer,
            #                     "ftHelper":ftHelper,
            #                     "featureIterator":featureIterator,
            #                     "memory":memory}
            self.createLayerInGeoPKG(memory,layer)
            self.fillLayer(layer, featureIterator,memory)

        # for layername, info in layerInfo.items():
        #     fiterator = info["featureIterator"]
        #     self.fillLayer(layername,fiterator)

    def fillLayer(self,layername,fiterator,memory):
        layer = QgsVectorLayer(self.fname+"|layername="+layername)
        layer_fields = layer.fields()
        diff_fields_names = [f.name() for f in memory.fields().toList()]

        BATCHSIZE = 100

        # batch the feature iterator
        def _batch(iterable, size):
            sourceiter = iter(iterable)
            while True:
                batchiter = islice(sourceiter, size)
                try:
                    yield chain([next(batchiter)], batchiter)
                except StopIteration:
                    return

        for batch in _batch(fiterator, BATCHSIZE):
            features = []
            for f in batch:
                features.extend(self.convertToGeoPKGFeature(f,layer_fields,diff_fields_names))  # convert to simple feature
            success,fs = layer.dataProvider().addFeatures(features)  # write to geopkg
            if not success:
                raise Exception("error writing DIFF to layer")

        sip.delete(layer)
        del layer

    def createLayerInGeoPKG(self,memory,layerName):
        actionOnExistingFile = 0 # create
        if os.path.exists(self.fname):
            actionOnExistingFile = 1  # append
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.layerName = layerName
        options.fileEncoding = "UTF-8"
        options.actionOnExistingFile = actionOnExistingFile
        errcode, errstr = QgsVectorFileWriter.writeAsVectorFormat(memory,
                                                                    self.fname,
                                                                    options
                                                                    )
        if errcode != 0:
            raise Exception("error writing diff - " + str(errcode) + " - " + errstr)

    def createMemoryDS(self,ftHelper,layerName):
        qgsfields, geomAtt = self.getFields(ftHelper)
        uri = "{}?crs={}".format(QgsWkbTypes.displayString(FeatureTypeHelper.typeNameConverter[geomAtt.type.lower()]),
                                 geomAtt.SRS)
        newlayer = QgsVectorLayer(uri, layerName, 'memory')

        with edit(newlayer):
            newlayer.dataProvider().addAttributes(qgsfields)
            newlayer.updateFields()
            newlayer.setCrs(QgsCoordinateReferenceSystem(geomAtt.SRS))
        return newlayer

    def getFields(self,ftHelper):
        # fields (from geogig)
        fields = ftHelper.newFeatureFields()
        geomAtt = ftHelper.newFeatureGeomField()  # geometry field (so we know if its POLYGON or LINESTRING...)
        # setup QgsFields object
        qgsfields = QgsFields()
        for f in fields:
            qgsfields.append(f)
        # add a differenciator
        #  added, deleted, modified.before, modified.after
        qgsfields.append(QgsField("GeoGig.ChangeType", QVariant.String))
        return qgsfields,geomAtt

    # source is
    # {
    #  'ID':<geogig ID - string>,
    #  'geogig.changeType':  - int 0=add,1=modify,2=delete,
    #  'old': <QgsFeature> -- old feature (None if add)
    #  'new': <QgsFeature> -- new feature (None if delete)
    # }
    # could return 1 or 2 features
    # 2 for modified
    def convertToGeoPKGFeature(self, feature,layer_fields,source_fields):
        changetype = feature["geogig.changeType"]
        if changetype == 0:  # add
            return [self.updateFeature(feature["new"], "added",layer_fields,source_fields)]
        elif changetype == 1:  # modify
            return [self.updateFeature(feature["old"], "modified.before",layer_fields,source_fields),
                    self.updateFeature(feature["new"], "modified.after",layer_fields,source_fields)
                    ]
        else:  # delete
            return [self.updateFeature(feature["old"], "deleted",layer_fields,source_fields)]

    # add a field to the feature (create a new one)
    def updateFeature(self, f, value,layer_fields,source_fields):
        feature_attributes = f.attributes()
        qfeat = QgsFeature()
        qfeat.setFields(layer_fields)
        qfeat.setGeometry(f.geometry())

        for f_indx, fname in enumerate(source_fields):
            if fname == "GeoGig.ChangeType":
                qfeat.setAttribute("GeoGig.ChangeType", value)
            else:
                qfeat.setAttribute(fname, feature_attributes[f_indx])

        return qfeat


class DiffGeoPKGMultiLayerForPR(DiffGeoPKGMultiLayer):

    def __init__(self, server, user, repo, prid,layer=None):
        self.server = server
        self.user = user
        self.repo = repo
        self.prid = prid
        if layer is not None:
            self.layers = [layer]
        else:
            self.layers = self.getLayers()
        self.fname = self._gpkgPath()

    def _gpkgPath(self):
        subfolder = "PRdiff-" + str(uuid.uuid4()).replace("-", "")
        path = os.path.join(os.path.dirname(QgsApplication.qgisUserDatabaseFilePath()),
                            "geogig", self.user, self.repo, "DIFF", subfolder)
        if not os.path.exists(path):
            os.makedirs(path)
        return os.path.join(path, "PR_DIFF_" + str(self.prid) + ".gpkg")

    def getLayers(self):
        total,r = self.server.diffSummaryPR(self.user,self.repo,self.prid)
        return [l["path"] for l in r.values()]

    def getDiff(self, layerName):
        return self.server.diffPR(self.user, self.repo, layerName, self.prid)

    def createAbstract(self, layerName):
        return "user: {}\nrepo: {}\nPR: {}\n".format(
            self.user, self.repo, str(self.prid)
        )

def clearDiffFiles():
    if pluginSetting("removedifffiles"):
        folder = pluginSetting("difffolder") or os.path.join(os.path.expanduser('~'), 'geogig', 'diff')
        shutil.rmtree(folder)