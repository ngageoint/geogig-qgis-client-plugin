from geogig.gui.conflictdialog import ConflictDialog
from geogig.utils import addFeatureToLayer
from qgis.core import QgsFeature

def solveConflicts(geogiglayer, diff):
    conflicts = {}
    for feature in diff:
        oldFeature = feature["old"]
        conflicts[feature["ID"]] = {}
        conflicts[feature["ID"]]["origin"] = oldFeature
        newFeature = feature["new"]
        if newFeature:
            conflicts[feature["ID"]]["remote"] = newFeature
        else:
            conflicts[feature["ID"]]["remote"] = None
        conflicts[feature["ID"]]["local"] = geogiglayer.getFeatureFromGeogigId(feature["ID"])
        
    allconflicts = {geogiglayer.layername: conflicts}
    dialog = ConflictDialog(allconflicts)
    dialog.exec_()
    if dialog.okToMerge:
        applyResolvedConflicts(geogiglayer, dialog.resolvedConflicts[geogiglayer.layername], conflicts)
        return True
    else:
        return False

def applyResolvedConflicts(geogiglayer, resolvedConflicts, conflicts):
    for fid, solved in resolvedConflicts.items():
        feature = geogiglayer.getFeatureFromGeogigId(fid)
        if feature:
            if feature.id() in geogiglayer.modifiedFeatures:
                geogiglayer.modifiedFeatures.remove(feature.id())
            geogiglayer.layer.dataProvider().deleteFeatures([feature.id()])
        else:
            geogiglayer.deletedFeatures.remove(fid)
        if solved is None:
            geogiglayer.deletedFeatures.append(fid)
        else:
            addFeatureToLayer(geogiglayer.layer, solved)
            solvedFeature = geogiglayer.getFeatureFromGeogigId(fid)
            geogiglayer.modifiedFeatures.append(solvedFeature.id())
