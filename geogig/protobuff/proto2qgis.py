from qgis.core import (QgsMessageLog, QgsFeature, QgsGeometry, QgsVectorLayer, QgsField, QgsCoordinateReferenceSystem,
                       QgsApplication,NULL)
#import geogig.protobuff.messages_pb2  as messages_pb2
messages_pb2 = None
from io import BytesIO
from geogig.utils import GEOGIGID_FIELD
from qgis.PyQt.QtCore import QVariant, QDateTime, QUuid, QDate

_VarintBytes = None

def typeNumbToBinding(fieldTypeNumb):
    if fieldTypeNumb == QVariant.String:
        return "STRING"
    if fieldTypeNumb == QVariant.LongLong:
        return "LONG"
    if fieldTypeNumb == QVariant.Double:
        return "DOUBLE"
    if fieldTypeNumb == QVariant.Int:
        return "INTEGER"
    if fieldTypeNumb == 38:  # QVariant.Float
        return "FLOAT"
    if fieldTypeNumb == QVariant.Bool:
        return "BOOLEAN"
    if fieldTypeNumb == 37:  # QVariant.UCharQVariant.String:
        return "BYTE"
    if fieldTypeNumb == 33:  # QVariant.Short
        return "SHORT"
    if fieldTypeNumb == 7:  # QVariant.QChar
        return "CHAR"
    if fieldTypeNumb == QVariant.Uuid:
        return "UUID"
    if fieldTypeNumb == QVariant.DateTime:
        return "DATETIME"
    if fieldTypeNumb == QVariant.Date:
        return "DATE"
    if fieldTypeNumb == QVariant.Time:
        return "TIME"
    # if fieldTypeNumb == QVariant.TimeStamp:
    #     return "TIMESTAMP"

    raise Exception("unknown qvariant type " + str(fieldTypeNumb))

def createQGISFeatureShell(f):
    qgeom = QgsGeometry()
    qgeom.fromWkb(f.geom)
    atts = [getValue(a) for a in f.value]
    atts.insert(0, f.ID)
    return qgeom,atts

# converts a GeoGig proto features -> QGIS feature
def createQGISFeature(f):
    qfeat = QgsFeature()
    qgeom = QgsGeometry()
    qgeom.fromWkb(f.geom)
    qfeat.setGeometry(qgeom)
    atts = [getValue(a) for a in f.value]
    atts.insert(0, f.ID)
    qfeat.setAttributes(atts)
    return qfeat


    # converts a proto3 feature (DIFF encoded)  to a
    # {
    #  'ID':<geogig ID - string>,
    #  'geogig.changeType':  - int 0=add,1=modify,2=delete,
    #  'old': <QgsFeature> -- old feature (None if add)
    #  'new': <QgsFeature> -- new feature (None if delete)
    # }
def createDiffFeature(f, ft):
    qfeat_old = None
    qfeat_new = None
    qfeat_old_atts = [f.ID]
    qfeat_new_atts = [f.ID]

    changeType = getValue(f.value[0])
    if changeType == 0 or changeType == 1:  # add or change
        qfeat_new = QgsFeature()
        qfeat_new.setFields(ft.newFeatureFields())
    if changeType == 2 or changeType == 1:  # del or change
        qfeat_old = QgsFeature()
        qfeat_old.setFields(ft.oldFeatureFields())

    result = {"ID": f.ID,
              "geogig.changeType": getValue(f.value[0]),
              "new": qfeat_new,
              "old": qfeat_old}
    for idx in range(0, len(ft.featureType.attribute)):
        att = ft.featureType.attribute[idx]
        if att.name == "geogig.changeType":
            continue
        if att.name.startswith("old.") and qfeat_old is not None:
            value = getValue(f.value[idx])
            if att.name.endswith("." + ft.featureType.defaultGeometryName):
                if value is not None:
                    qfeat_old.setGeometry(value)
            else:
                qfeat_old_atts.append(value)
        elif att.name.startswith("new.") and qfeat_new is not None:
            value = getValue(f.value[idx])
            if att.name.endswith("." + ft.featureType.defaultGeometryName):
                if value is not None:
                    qfeat_new.setGeometry(value)
            else:
                qfeat_new_atts.append(value)
    if qfeat_new is not None:
        qfeat_new.setAttributes(qfeat_new_atts)
    if qfeat_old is not None:
        qfeat_old.setAttributes(qfeat_old_atts)
    return result


def createConflictFeature(f, ft):
    qfeat_ancestor = None
    qfeat_ours = None
    qfeat_theirs = None

    qfeat_ancestor_atts = [f.ID]
    qfeat_ours_atts = [f.ID]
    qfeat_theirs_atts = [f.ID]

    code = getValue(f.value[0])
    if (code & 0x01):
        qfeat_ancestor = QgsFeature()
        qfeat_ancestor.setFields(ft.conflictFeatureFields())
    if (code & 0x02):
        qfeat_ours = QgsFeature()
        qfeat_ours.setFields(ft.conflictFeatureFields())
    if (code & 0x04):
        qfeat_theirs = QgsFeature()
        qfeat_theirs.setFields(ft.conflictFeatureFields())

    for idx in range(0, len(ft.featureType.attribute)):
        att = ft.featureType.attribute[idx]
        if att.name == "geogig.conflictType":
            continue
        if att.name.startswith("ancestor.") and qfeat_ancestor is not None:
            value = getValue(f.value[idx])
            if att.name.endswith("." + ft.featureType.defaultGeometryName):
                if value is not None:
                    qfeat_ancestor.setGeometry(value)
            else:
                qfeat_ancestor_atts.append(value)
        elif att.name.startswith("ours.") and qfeat_ours is not None:
            value = getValue(f.value[idx])
            if att.name.endswith("." + ft.featureType.defaultGeometryName):
                if value is not None:
                    qfeat_ours.setGeometry(value)
            else:
                qfeat_ours_atts.append(value)
        elif att.name.startswith("theirs.") and qfeat_theirs is not None:
            value = getValue(f.value[idx])
            if att.name.endswith("." + ft.featureType.defaultGeometryName):
                if value is not None:
                    qfeat_theirs.setGeometry(value)
            else:
                qfeat_theirs_atts.append(value)

    if qfeat_ancestor is not None:
        qfeat_ancestor.setAttributes(qfeat_ancestor_atts)
    if qfeat_ours is not None:
        qfeat_ours.setAttributes(qfeat_ours_atts)
    if qfeat_theirs is not None:
        qfeat_theirs.setAttributes(qfeat_theirs_atts)

    result = {"ID": f.ID,
              "ancestor": qfeat_ancestor,
              "theirs": qfeat_theirs,
              "ours":qfeat_ours}

    return result

# handle the proto one-of fields
def getValue(val):
    value_type = val.WhichOneof('value_type')
    if value_type == 'null_value':
        return None
    elif value_type == 'string_value':
        return val.string_value
    elif value_type == 'int_value':
        return val.int_value
    elif value_type == 'long_value':
        return val.long_value
    elif value_type == 'bool_value':
        return val.bool_value
    elif value_type == 'double_value':
        return val.double_value
    elif value_type == 'float_value':
        return val.foat_value
    elif value_type == "geom_value":
        if len(val.geom_value) == 0:
            return None
        qgeom = QgsGeometry()
        qgeom.fromWkb(val.geom_value)
        return qgeom
    elif value_type == "byte_value":
        return val.byte_value
    elif value_type == "short_value":
        return val.short_value
    elif value_type == "char_value":
        return (val.char_value)
    elif value_type == "uuid_value":
        return QUuid(val.uuid_value)
    elif value_type == "datetime_value":
        return QDateTime.fromMSecsSinceEpoch(val.datetime_value)
    elif value_type == "date_value":
        dt = QDateTime.fromMSecsSinceEpoch(val.date_value)
        return dt.date()
    elif value_type == "time_value":
        dt = QDateTime.fromMSecsSinceEpoch(val.time_value)
        return dt.time()
    elif value_type == "timestamp_value":
        ts = val.timestamp_value
        dt = QDateTime.fromMSecsSinceEpoch(ts.seconds*1000)
        dt.addMSecs(ts.nanos/1000000)
        return dt.time()


class FeatureWriter:
    # geom -- geogig default geometry attribute name (assumed for gpkg)
    # geomName needs to be either the actual geometry column name in geogig, or "@geometry"
    def __init__(self, features, typename="", geomName="@geometry", geometryType="GEOMETRY", srs=""):
        global messages_pb2
        if messages_pb2 is None:
            import geogig.protobuff.messages_pb2  as messages_pb2
        self.features = features
        self.attName = []
        self.attTypeNumbs = []

        self.featureType = messages_pb2.FeatureType()
        self.featureType.featureTypeName = typename
        self.featureType.defaultGeometryName = geomName
        f = features[0]  # assume at least one!
        for field in features[0].fields().toList():
            fieldName = field.name()
            if fieldName == GEOGIGID_FIELD:  # this isn't a real property
                continue

            fieldTypeNumb = field.type()  # number representing type
            if fieldTypeNumb == 2: #int
                if field.typeName() == "int2" or field.typeName() == "int16":
                    fieldTypeNumb=33 # remake as short
            if fieldTypeNumb == QVariant.Double: #floating point
                if field.typeName() == "float4" or field.typeName() == "float32":
                    fieldTypeNumb = 38  # remake as float
            self.attName.append(fieldName)
            self.attTypeNumbs.append(fieldTypeNumb)
            binding = typeNumbToBinding(fieldTypeNumb)
            att = self.featureType.attribute.add()
            att.name = fieldName
            att.type = binding

        att = self.featureType.attribute.add()
        att.name = geomName
        att.type = geometryType

    def asBytes(self):
        global _VarintBytes
        if _VarintBytes is None:
             from google.protobuf.internal.encoder import _VarintBytes

        result = BytesIO()

        ft_bytes = self.featureType.SerializeToString()
        ft_size_bytes = _VarintBytes(len(ft_bytes))
        result.write(ft_size_bytes)
        result.write(ft_bytes)

        for f in self.features:
            f_bytes = self.convertFeature(f).SerializeToString()
            f_size_bytes = _VarintBytes(len(f_bytes))
            result.write(f_size_bytes)
            result.write(f_bytes)
        return result.getvalue()

    # convert to the proto feature
    def convertFeature(self, qgsfeature):
        global messages_pb2 # will be set in __init__
        feature = messages_pb2.Feature()
        feature.geom = qgsfeature.geometry().asWkb().data()
        try:
            feature.ID = qgsfeature[GEOGIGID_FIELD] or ""
        except KeyError:
            feature.ID = "" 
        for idx in range(0, len(self.attTypeNumbs)):
            att = feature.value.add()
            self.convert(att, qgsfeature[self.attName[idx]], self.attTypeNumbs[idx])
        return feature

    def convert(self, result, qvar, fieldTypeNumb):
        if qvar == NULL:
            result.null_value = True
            return result

        if fieldTypeNumb == QVariant.LongLong:
            result.long_value = qvar
        elif fieldTypeNumb == QVariant.Double:
            result.double_value = qvar
        elif fieldTypeNumb == QVariant.Int:
            result.int_value = qvar
        elif fieldTypeNumb == 38: # QVariant.Float
            result.float_value = qvar
        elif fieldTypeNumb == QVariant.Bool:
            result.bool_value = qvar
        elif fieldTypeNumb == QVariant.String:
            result.string_value = qvar

        elif fieldTypeNumb == 37: # QVariant.UChar = Byte
            result.char_value = qvar
        elif fieldTypeNumb == 33: # QVariant.Short
            result.short_value = qvar
        elif fieldTypeNumb == 7: # QVariant.QChar
            result.char_value = qvar
        elif fieldTypeNumb ==  QVariant.Uuid:
            result.uuid_value = qvar.toString()
        elif fieldTypeNumb == QVariant.DateTime:
            result.datetime_value = qvar.toMSecsSinceEpoch()
        elif fieldTypeNumb == QVariant.Date:
            dt = QDateTime(qvar)
            #dt.setTimeSpec(1) # Qt::UTC
            result.date_value = dt.toMSecsSinceEpoch()
        elif fieldTypeNumb == QVariant.Time:
            result.time_value = qvar.msecsSinceStartOfDay()
        #timestamp -> not handled

        else:
            raise Exception("unknown qvariant type " + str(fieldTypeNumb))
        return result



