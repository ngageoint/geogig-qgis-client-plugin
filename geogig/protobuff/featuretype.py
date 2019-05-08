import time
from itertools import islice, chain
#import geogig.protobuff.messages_pb2  as messages_pb2
import geogig.layers

messages_pb2 = None
from qgis.core import (QgsVectorLayer, QgsField, QgsCoordinateReferenceSystem, QgsFeature, 
                        QgsMessageLog, QgsWkbTypes, QgsVectorFileWriter, edit, QgsFields)
from  qgis.PyQt.QtCore import QVariant
from geogig.protobuff.streamingprotohelper import readSize
from geogig.utils import GEOGIGID_FIELD
from copy import copy
from geogig.geopkgtools import *
import sip
from geogig.geopkgtools import clearAuditTables

class FeatureTypeHelper:

    typeNameConverter = {
        'linestring':QgsWkbTypes.LineString,
        'point':QgsWkbTypes.Point,
        'polygon' : QgsWkbTypes.Polygon,
        'multilinestring': QgsWkbTypes.MultiLineString,
        'multipoint': QgsWkbTypes.MultiPoint,
        'multipolygon': QgsWkbTypes.MultiPolygon
    }

    def __init__(self, reader):
        global messages_pb2
        if messages_pb2 is None:
            import geogig.protobuff.messages_pb2  as messages_pb2
        # reads in a FT message
        length_ft = readSize(reader)
        buff = reader.read(length_ft)
        ft = messages_pb2.FeatureType()
        ft.ParseFromString(buff)
        self.featureType = ft

    def newFeatureFields(self):
        nonGeomAtts = [a for a in self.featureType.attribute if (a.name.startswith("new.") and 
                        a.name != "new." + self.featureType.defaultGeometryName)]
        fields = [self.createField(a) for a in nonGeomAtts] 
        fields.insert(0, QgsField(GEOGIGID_FIELD, QVariant.String))       
        qgsfields = QgsFields()
        for f in fields:
            qgsfields.append(f)
        return qgsfields

    def conflictFeatureFields(self):
        nonGeomAtts = [a for a in self.featureType.attribute if (a.name.startswith("ancestor.") and
                                                                 a.name != "ancestor." + self.featureType.defaultGeometryName)]
        fields = [self.createField(a) for a in nonGeomAtts]
        fields.insert(0, QgsField(GEOGIGID_FIELD, QVariant.String))
        qgsfields = QgsFields()
        for f in fields:
            qgsfields.append(f)
        return qgsfields

    def newFeatureGeomField(self):
        geomAtt = [a for a in self.featureType.attribute if a.name == "new." + self.featureType.defaultGeometryName][0]
        return geomAtt

    def oldFeatureFields(self):
        nonGeomAtts = [a for a in self.featureType.attribute if (a.name.startswith("old.") and 
                        a.name != "old." + self.featureType.defaultGeometryName)]
        fields = [self.createField(a) for a in nonGeomAtts]
        fields.insert(0, QgsField(GEOGIGID_FIELD, QVariant.String))
        qgsfields = QgsFields()
        for f in fields:
            qgsfields.append(f)
        return qgsfields

    def getFields(self):
        fields, geomAtt = self._fields()
        result = QgsFields()
        for field in fields:
            result.append(field)
        return result

    def _fields(self):
        if self.featureType.defaultGeometryName is None or self.featureType.defaultGeometryName == '':
            geomAtt = None
        else:
            geomAtt = [a for a in self.featureType.attribute if a.name == self.featureType.defaultGeometryName][0]
        nonGeomAtts = [a for a in self.featureType.attribute if a.name != self.featureType.defaultGeometryName]
        fields = [self.createField(a) for a in nonGeomAtts]
        fields.insert(0, QgsField(GEOGIGID_FIELD, QVariant.String))
        return fields, geomAtt

    def overwriteGeopkgLayer(self, filepath, featureIterator, layername):
        dropTable(filepath,layername)
        self.createGeopkgLayer(filepath, featureIterator)
        geogig.layers.announceGeoPKGUpdated(filepath)

    def createGeopkgLayer(self, filepath, featureIterator):
        fields, geomAtt = self._fields()
        qgsfields = QgsFields()
        for f in fields:
            qgsfields.append(f)
        writer = QgsVectorFileWriter(filepath, "UTF-8", qgsfields, FeatureTypeHelper.typeNameConverter[geomAtt.type.lower()], 
                                    QgsCoordinateReferenceSystem(geomAtt.SRS), driverName = "GPKG")
        
        BATCHSIZE = 500
        def _batch(iterable, size):
            sourceiter = iter(iterable)
            while True:
                batchiter = islice(sourceiter, size)
                try:
                    yield chain([next(batchiter)], batchiter)
                except StopIteration:
                    return                    
        for batch in _batch(featureIterator, BATCHSIZE):
            success = writer.addFeatures(batch)
            if not success:
                error = writer.errorMessage()
                del writer
                raise Exception("geopkg save: " + error)
        writer.flushBuffer()
        # the only way to close the writer is to call the C++ destructor -- we use sip to do this
        sip.delete(writer)
        del writer # remove from python
        addAuditTables(filepath)

    def createMemLayer(self, featureIterator):
        # create a memory layer, given a feature type and the features that go in it
        fields, geomAtt = self._fields()
        layerName = self.featureType.featureTypeName
        if geomAtt is None:
            uri = "None"
        else:
            uri = "{}?crs={}".format(QgsWkbTypes.displayString(FeatureTypeHelper.typeNameConverter[geomAtt.type.lower()]),
                                geomAtt.SRS)
        newlayer = QgsVectorLayer(uri, layerName, 'memory')

        with edit(newlayer):
            newlayer.dataProvider().addAttributes(fields)
            newlayer.updateFields()
            features =list(featureIterator)
            newlayer.addFeatures(features)
            if geomAtt is not None:
                newlayer.setCrs(QgsCoordinateReferenceSystem(geomAtt.SRS))
        return newlayer

    # given the proto3 Value encoding, create a corresponding type for QGIS
    #http://doc.qt.io/qt-5/qmetatype.html#Type-enum
    def createField(self, ft_attribute):
        typename = None
        if ft_attribute.type == "LONG":
            variant = QVariant.LongLong
        elif ft_attribute.type == "DOUBLE":
            variant = QVariant.Double
        elif ft_attribute.type == "FLOAT":
            variant = QVariant.Double # QVariant.Float
            typename = "float4"
        elif ft_attribute.type == "INTEGER":
            variant = QVariant.Int
        elif ft_attribute.type == "BOOLEAN":
            variant = QVariant.Bool
        elif ft_attribute.type == "STRING":
            variant = QVariant.String
        elif ft_attribute.type == "BYTE":
            variant = 37 # QVariant.UChar= Byte
        elif ft_attribute.type == "SHORT":
            variant = QVariant.Int # QVariant.Short
            typename = "int2"
        elif ft_attribute.type == "CHAR":
            variant = 7 # QVariant.QChar
        elif ft_attribute.type == "UUID":
            variant = QVariant.Uuid
        elif ft_attribute.type == "DATETIME":
            variant = QVariant.DateTime
        elif ft_attribute.type == "DATE":
            variant = QVariant.Date
        elif ft_attribute.type == "TIME":
            variant = QVariant.Time
        elif ft_attribute.type == "TIMESTAMP":
            variant = QVariant.DateTime   # NOTE: this will cause issues when writing, but ...
        else:
            raise Exception("unknown type -" + ft_attribute.type)

        name = ft_attribute.name 
        if name.startswith("new.") or name.startswith("old."):
            name = name[4:]
        elif name.startswith("ancestor."):
            name = name[9:]
        elif name.startswith("theirs."):
            name = name[7:]
        elif name.startswith("ours."):
            name = name[5:]
        field= QgsField(name, variant)
        if typename is not None:
            field.setTypeName(typename)
        return field
