#import geojson
import json
from qgis.core import QgsGeometry, QgsFeature, QgsFeatureRequest, QgsExpression, QgsEditorWidgetSetup


GEOGIGID_FIELD = "geogigid"

def hideGeogigidField(layer):
    config = layer.attributeTableConfig()
    columns = config.columns()
    for i, column in enumerate(columns):
        if column.name == GEOGIGID_FIELD:
            config.setColumnHidden(i, True)
            break
    layer.setAttributeTableConfig(config)
    layer.setEditorWidgetSetup(layer.fields().indexFromName(GEOGIGID_FIELD),QgsEditorWidgetSetup("Hidden",{}))
    pass


def getFeaturesFromGeogigIds(gigids, layer):
    fids = ["'"+fid+"'" for fid in gigids]
    fids = ",".join(fids)
    features = list(layer.getFeatures(QgsFeatureRequest(
                            QgsExpression('"{}" in ({})'.format(GEOGIGID_FIELD, fids)))))
    return {f[GEOGIGID_FIELD]:f for f in features}

def getFeatureFromGeogigId(fid, layer):
    features = list(layer.getFeatures(QgsFeatureRequest(
                            QgsExpression('"{}"=\'{}\''.format(GEOGIGID_FIELD, fid)))))
    if features:
        return features[0]
    else:
        return None

def addFeatureToLayer(layer, feature):
    newFeature = QgsFeature()
    newFeature.setFields(layer.fields())
    for f in feature.fields().toList():
        newFeature.setAttribute(f.name(), feature[f.name()])
    newFeature.setGeometry(feature.geometry())
    layer.dataProvider().addFeatures([newFeature])

def addFeaturesToLayer(layer, features):
    toadd =[]
    for feature in features:
        newFeature = QgsFeature()
        newFeature.setFields(layer.fields())
        for f in feature.fields().toList():
            newFeature.setAttribute(f.name(), feature[f.name()])
        newFeature.setGeometry(feature.geometry())
        toadd.append(newFeature)
    layer.dataProvider().addFeatures(toadd)

def replaceFeatureInLayer(layer, oldFeature, feature):
    attrs = {}
    for i, f in enumerate(oldFeature.fields().toList()):
        try:
            attrs[i] = feature[f.name()]
        except KeyError:
            attrs[i] = oldFeature[i]
    r = layer.dataProvider().changeAttributeValues({oldFeature.id(): attrs})
    r = layer.dataProvider().changeGeometryValues({oldFeature.id(): feature.geometry()})
    pass

def replaceFeaturesInLayer(layer, oldFeatures, features):
    if not oldFeatures:
        return # no action

    fields = None
    attChanges = {}
    geomChanges = {}

    for gigid, f_old in oldFeatures.items():
        f_new = features[gigid]
        if fields is None:
            fields = f_old.fields().toList()

        attrs = {}
        for i, f in enumerate(fields):
            try:
                attrs[i] = f_new[f.name()]
            except KeyError:
                attrs[i] = f_old[i]
        id = f_old.id()
        attChanges[id] = attrs
        geomChanges[id] = f_new.geometry()
    r = layer.dataProvider().changeAttributeValues(attChanges)
    r = layer.dataProvider().changeGeometryValues(geomChanges)
    pass