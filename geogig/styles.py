import re
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import QgsMapLayer

def saveStyleFromQgisLayer(layer, server, user, repo):
    doc = QDomDocument()
    layer.exportNamedStyle(doc, categories=QgsMapLayer.Symbology | QgsMapLayer.Labeling)
    server.addStyle(user, repo, layer.name(), doc.toString())

def saveStyle(geogiglayer):
    doc = QDomDocument()
    geogiglayer.layer.exportNamedStyle(doc, categories=QgsMapLayer.Symbology | QgsMapLayer.Labeling)    
    geogiglayer.server.addStyle(geogiglayer.user, geogiglayer.repo, geogiglayer.layername, doc.toString())

def setStyle(geogiglayer):
    try:
        style = geogiglayer.server.getStyle(geogiglayer.user, geogiglayer.repo, geogiglayer.layername)
        doc = QDomDocument()
        doc.setContent(style)
        geogiglayer.layer.importNamedStyle(doc, categories=QgsMapLayer.Symbology | QgsMapLayer.Labeling)
    except Exception as e:
        print(e)
        pass