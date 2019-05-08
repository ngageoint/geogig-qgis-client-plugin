from geogig.layers.geogiglivelayer import GeogigLiveLayer
from geogig.layers.geogiglayer import GeogigLayer
from geogig.layers.geogiggpkglayer import GeogigGpkgLayer
from geogig.geogigwebapi.connector import GeogigError
from geogig.geogigwebapi.server import Server
from geogig.geogigwebapi.connector import getConnector
from geogig.gui.extentdialog import ExtentDialog
import geogig.geopkgtools
# from geogig.geopkgtools import getMetadataValue, simplifyGeoPKGFname
from qgis.core import QgsProject, QgsRectangle, QgsEditorWidgetSetup
from geogig.crs import xform
from qgis.utils import *

_geogigLayers = []


def announceGeoPKGUpdated(fname):
    fname = os.path.normcase(os.path.realpath(os.path.expanduser(geogig.geopkgtools.simplifyGeoPKGFname(fname))))
    for layer in _geogigLayers:
        if isinstance(layer, GeogigGpkgLayer):
            fname_layer =  os.path.normcase(os.path.realpath(os.path.expanduser(geogig.geopkgtools.simplifyGeoPKGFname(layer.gpkgPath))))
            if fname == fname_layer:
                layer.layer.dataProvider().dataChanged.emit()



def addGeogigLayer(server, user, repo, layername, commitid, live, parent = None):
    if live:
        layer = GeogigLiveLayer(server, user, repo, layername, commitid)
    else:
        parent = parent or iface.mainWindow()
        if parent == iface:
            parent = iface.mainWindow()
        dlg = ExtentDialog(parent)
        dlg.exec_()
        if dlg.ok:
            extent = dlg.extent
            if extent is not None:
                extentRect = QgsRectangle(extent[0],extent[1],
                                      extent[2],extent[3])
                projectCrs = QgsProject.instance().crs()
                layerCrs = server.layerCrs(user, repo, layername, commitid)
                extentRect = xform(extentRect, projectCrs,layerCrs)
                extent = [extentRect.xMinimum(),extentRect.yMinimum(),
                          extentRect.xMaximum(), extentRect.yMaximum()]
            layer = GeogigGpkgLayer(server, user, repo, layername, commitid, extent=extent)
        else:
            return False # no action - they said "cancel"
    _geogigLayers.append(layer)
    if live and not layer.isValid(): # layer will not be valid/invalid until downloaded -- will do check then
        raise GeogigError("Could not populate layer with Geogig server data. See log for details", "Error connecting to server")
    return True

def addGeogigLayerFromLayer(layer):
    if getWrappingGeogigLayer(layer) is not None:        
            return
    classes = {GeogigLiveLayer.__name__: GeogigLiveLayer,
                GeogigGpkgLayer.__name__: GeogigGpkgLayer}
    url = layer.customProperty(GeogigLayer.GEOGIG_URL)
    username = None
    password = None
    user = layer.customProperty(GeogigLayer.GEOGIG_USER)
    repo = layer.customProperty(GeogigLayer.GEOGIG_REPO)
    layername = layer.customProperty(GeogigLayer.GEOGIG_LAYER)
    commitid = layer.customProperty(GeogigLayer.GEOGIG_COMMITID)    
    bounds = None
    extent = layer.customProperty(GeogigLayer.GEOGIG_EXTENT)
    if extent is not None:
        bounds = [float(b) for b in extent]
    classname = layer.customProperty(GeogigLayer.GEOGIG_LAYERCLASS)
    server = Server.getInstance(getConnector(url))
    return classes[classname](server, user, repo, layername, commitid, layer, bounds)            

def layersRemoved(ids):
    for layer in _geogigLayers[::-1]:
        if layer.layer.id() in ids:
            _geogigLayers.remove(layer)
            layer.cleanup()

def isGeogigLayer(layer):
    return any([layer.id() == lay.layer.id() for lay in _geogigLayers])

def getWrappingGeogigLayer(layer):
    for gglayer in _geogigLayers:
        if gglayer.layer.id() == layer.id():
            return gglayer

def isLiveLayer(layer):
    return any([layer.id() == lay.layer.id() and isinstance(lay, GeogigLiveLayer) for lay in _geogigLayers])

def refreshGeogigLayers():
    ids = [lay.id() for lay in list(QgsProject.instance().mapLayers().values())]
    global _geogigLayers
    for layer in _geogigLayers:
        if layer.layer.id() in ids and isinstance(layer, GeogigLiveLayer):
            layer.refresh(forceRefresh = False)

def onLayersLoaded(layers):
    global _geogigLayers
    for layer in layers:
        if GeogigLiveLayer.GEOGIG_URL in layer.customPropertyKeys(): #geogig layer that is part of a project
            geogigLayer = addGeogigLayerFromLayer(layer)
            if geogigLayer:
                _geogigLayers.append(geogigLayer)
                if not geogigLayer.isValid():
                    item = QgsProject.instance().layerTreeRoot().findLayer(geogigLayer.layer.id())
                    item.setItemVisibilityCheckedRecursive(False)
                    raise GeogigError("Could not populate layer with Geogig server data")
        else: #let's see if it's a geogig layer in a geopackage file
            path = geogig.geopkgtools.simplifyGeoPKGFname(layer.source())
            if path.endswith("gpkg"):
                url = geogig.geopkgtools.getMetadataValue(path, GeogigLiveLayer.GEOGIG_URL)
                if url is not None:
                    rect = layer.extent()
                    extent = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]
                    layer.setCustomProperty(GeogigLiveLayer.GEOGIG_URL, url)
                    layer.setCustomProperty(GeogigLiveLayer.GEOGIG_USER, geogig.geopkgtools.getMetadataValue(path, GeogigLiveLayer.GEOGIG_USER))
                    layer.setCustomProperty(GeogigLiveLayer.GEOGIG_REPO, geogig.geopkgtools.getMetadataValue(path, GeogigLiveLayer.GEOGIG_REPO))
                    layer.setCustomProperty(GeogigLiveLayer.GEOGIG_LAYER, geogig.geopkgtools.getMetadataValue(path, GeogigLiveLayer.GEOGIG_LAYER))
                    layer.setCustomProperty(GeogigLiveLayer.GEOGIG_COMMITID, geogig.geopkgtools.getMetadataValue(path, GeogigLiveLayer.GEOGIG_COMMITID))
                    layer.setCustomProperty(GeogigLiveLayer.GEOGIG_EXTENT, extent)
                    layer.setCustomProperty(GeogigLiveLayer.GEOGIG_LAYERCLASS, GeogigGpkgLayer.__name__)
                    geogigLayer = addGeogigLayerFromLayer(layer)
                    if geogigLayer:
                        _geogigLayers.append(geogigLayer)
                        if not geogigLayer.isValid():
                            item = QgsProject.instance().layerTreeRoot().findLayer(geogigLayer.layer.id())
                            item.setItemVisibilityCheckedRecursive(False)
                            raise GeogigError("Could not populate layer with Geogig server data")

