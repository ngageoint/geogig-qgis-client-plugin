# -*- coding: utf-8 -*-

from builtins import object

import os
import sys

from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton, QMessageBox, QApplication

from qgis.core import QgsProject, QgsApplication, Qgis, QgsMessageLog, QgsSettings
from qgis import utils 

from qgiscommons2.gui import addAboutMenu, removeAboutMenu, addHelpMenu, removeHelpMenu
from qgiscommons2.settings import readSettings, pluginSetting, setPluginSetting
from qgiscommons2.gui.settings import addSettingsMenu, removeSettingsMenu
#from qgiscommons2.files import removeTempFolder

from geogig.layers import refreshGeogigLayers, layersRemoved, onLayersLoaded
from geogig.geogigwebapi.connector import GeogigAuthException, GeogigError
from geogig.gui.progressbar import currentWindow
from geogig.gui.navigatordialog import navigatorInstance
from geogig.infotool import MapToolGeoGigInfo
from geogig.layers.diffgeopkglayer import clearDiffFiles

class GeoGigPlugin(object):

    def __init__(self, iface):
        self.iface = iface
        readSettings()
        self.initConfigParams()
        sys.excepthook = self.excepthook
        self.askToSaveMemoryLayers = QgsSettings().value("askToSaveMemoryLayers", True, section=QgsSettings.App)
        QgsSettings().setValue("askToSaveMemoryLayers", False, section=QgsSettings.App)

    def initConfigParams(self):
        folder = pluginSetting("gpkgfolder")
        if folder.strip() == "":
            setPluginSetting("gpkgfolder", os.path.join(os.path.expanduser('~'), 'geogig', 'repos'))
        folder = pluginSetting("difffolder")
        if folder.strip() == "":
            setPluginSetting("difffolder", os.path.join(os.path.expanduser('~'), 'geogig', 'diff'))

    def unload(self):
        navigatorInstance.setVisible(False)
        
        self.iface.removePluginMenu("&GeoGig", self.explorerAction)

        removeHelpMenu("GeoGig")
        removeAboutMenu("GeoGig")
        removeSettingsMenu("GeoGig")

        #removeTempFolder()

        clearDiffFiles()

        self.iface.mapCanvas().extentsChanged.disconnect(refreshGeogigLayers)
        QgsProject.instance().layersWillBeRemoved.disconnect(layersRemoved)
        QgsProject.instance().legendLayersAdded.disconnect(onLayersLoaded)

        sys.excepthook = utils.qgis_excepthook 

        QgsSettings().setValue("askToSaveMemoryLayers", self.askToSaveMemoryLayers, section=QgsSettings.App)

    def initGui(self):
        icon = QIcon(os.path.dirname(__file__) + "/ui/resources/geogig.png")
        self.explorerAction = navigatorInstance.toggleViewAction()
        self.explorerAction.setIcon(icon)
        self.explorerAction.setText("GeoGig Navigator")

        self.iface.addPluginToMenu("&GeoGig", self.explorerAction)

        icon = QIcon(os.path.dirname(__file__) + "/ui/resources/identify.png")
        self.toolAction = QAction(icon, "GeoGig Feature Info Tool", self.iface.mainWindow())
        self.toolAction.setCheckable(True)
        self.toolAction.triggered.connect(self.setTool)

        self.iface.addPluginToMenu("&GeoGig", self.toolAction)

        addSettingsMenu("GeoGig")
        addHelpMenu("GeoGig")
        addAboutMenu("GeoGig")

        self.mapTool = MapToolGeoGigInfo(self.iface.mapCanvas())

        self.iface.addDockWidget(Qt.RightDockWidgetArea, navigatorInstance)

        self.iface.mapCanvas().extentsChanged.connect(refreshGeogigLayers)
        QgsProject.instance().layersWillBeRemoved.connect(layersRemoved)
        QgsProject.instance().legendLayersAdded.connect(onLayersLoaded)

    def setTool(self):
        self.toolAction.setChecked(True)
        self.iface.mapCanvas().setMapTool(self.mapTool)

    def excepthook(self, extype, value, tb):
        currentWindow().messageBar().clearWidgets()
        QApplication.restoreOverrideCursor()
        if extype == GeogigAuthException:
            currentWindow().messageBar().pushMessage("Geogig", "Wrong or missing credentials", level=Qgis.Warning, duration=5)
        elif extype == GeogigError:
            currentWindow().messageBar().pushMessage("Geogig", str(value), level=Qgis.Warning, duration=5)
            if value.details is not None:
                QgsMessageLog.logMessage("{}:{}".format(str(value), value.details), level=Qgis.Critical)
        else:
            utils.qgis_excepthook(extype, value, tb)
