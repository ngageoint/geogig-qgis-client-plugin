# -*- coding: utf-8 -*-

import os
import sys

from qgis.core import QgsGeometry, QgsFeature
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSettings, QSize, QVariant
from qgis.PyQt.QtGui import QIcon, QFont,QColor
from qgis.PyQt.QtWidgets import (QHBoxLayout,
                                 QTreeWidgetItem,
                                 QMessageBox,
                                 QTableWidgetItem,
                                 QPushButton,
                                 QHeaderView, QTreeWidgetItemIterator)

from geogig.extlibs.qgiscommons2.layers import loadLayerNoCrsDialog
from geogig.extlibs.qgiscommons2.gui import execute

resourcesPath = os.path.join(os.path.dirname(__file__), os.pardir, "resources")
ptOursStyle = os.path.join(resourcesPath, "pt_ours.qml")
ptTheirsStyle = os.path.join(resourcesPath, "pt_theirs.qml")
lineOursStyle = os.path.join(resourcesPath, "line_ours.qml")
lineTheirsStyle = os.path.join(resourcesPath, "line_theirs.qml")
polygonOursStyle = os.path.join(resourcesPath, "polygon_ours.qml")
polygonTheirsStyle = os.path.join(resourcesPath, "polygon_theirs.qml")

layerIcon = QIcon(os.path.join(os.path.dirname(__file__), os.pardir, "ui", "resources", "geometry.png"))
solvedConflictIcon = QIcon(os.path.join(os.path.dirname(__file__), os.pardir, "ui", "resources", "solved.png"))
unsolvedConflictIcon = QIcon(os.path.join(os.path.dirname(__file__), os.pardir, "ui", "resources", "conflicted.png"))

sys.path.append(os.path.dirname(__file__))
pluginPath = os.path.split(os.path.dirname(__file__))[0]
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'conflictdialog.ui'))


class ConflictDialog(WIDGET, BASE):

    # None - don't do anything (normal)
    # ConflictDialog.TEST_CASE_OVERRIDE = < LOCAL, REMOTE, OR DELETE >
    TEST_CASE_OVERRIDE = None



    LOCAL, REMOTE, DELETE = 1, 2, 3

    def __init__(self, conflicts, localName="Local", remoteName="Remote", changesName="Changes"):
        super(ConflictDialog, self).__init__(None)
        self.okToMerge=False # all resolved
        self.executeMerge = False # merge these conflict changes (user pressed "merge" not quit)

        # main result - this is
        # resolvedConflicts[layername][FID] = INT or QgsFeature
        #   INT ->  LOCAL, REMOTE, DELETE = 1, 2, 3
        #   QgsFeature -> merged (new) feature
        self.resolvedConflicts = {}
        self.conflicts = conflicts
        self.setupUi(self)

        self.attributesTable.setSortingEnabled(False)
        self.conflictsTree.itemClicked.connect(self.treeItemClicked)
        self.attributesTable.cellClicked.connect(self.cellClicked)
        self.solveAllLocalButton.clicked.connect(self.solveAllLocal)
        self.solveAllRemoteButton.clicked.connect(self.solveAllRemote)
        self.solveLocalButton.clicked.connect(self.solveLocal)
        self.solveRemoteButton.clicked.connect(self.solveRemote)
        self.mergePRButton.clicked.connect(self.mergePR)
        self.mergePRButton.setEnabled(False)

        self.lastSelectedItem = None
        self.currentPath = None
        self.currentLayer = None
        self.currentConflict = None

        self.solveLocalButton.setEnabled(False)
        self.solveRemoteButton.setEnabled(False)

        self.fillConflictsTree()
        self.conflictsTree.expandToDepth(3)
        self.localName = localName
        self.remoteName = remoteName
        self.changesName = changesName
        self.rename()

        self.autoSelectFirstConflict()
        if ConflictDialog.TEST_CASE_OVERRIDE is not None:
            self.resolveAll(ConflictDialog.TEST_CASE_OVERRIDE)
            self.executeMerge = True

    def exec_(self):
        if ConflictDialog.TEST_CASE_OVERRIDE is None:
            super(ConflictDialog, self).exec_()

    # select the first conflict in the list (nice for users)
    def autoSelectFirstConflict(self):
        iterator = QTreeWidgetItemIterator(self.conflictsTree)
        while iterator.value():
            item = iterator.value()
            if isinstance(item, ConflictItem):
                self.conflictsTree.setCurrentItem(item)
                self.treeItemClicked()
                return
            iterator += 1


    def mergePR(self):
        self.executeMerge = True
        self.close()

    # allow columns to be renamed so we can easily re-use this for other situations
    def rename(self):
        self.solveAllRemoteButton.setText(self.remoteName)
        self.solveRemoteButton.setText("Solve from " + self.remoteName + " feature")

        self.solveAllLocalButton.setText(self.localName)
        self.solveLocalButton.setText("Solve from " + self.localName + " feature")

        self.mergePRButton.setText("Merge " + self.changesName)

        self.attributesTable.setHorizontalHeaderLabels(["Before Change", self.remoteName,self.localName, "Attribute", "Merged"])


    def fillConflictsTree(self):
        self.treeItems = {}
        for path, conflicts in self.conflicts.items():
            topItem = QTreeWidgetItem()
            topItem.setText(0, path)
            topItem.setIcon(0, layerIcon)
            self.conflictsTree.addTopLevelItem(topItem)
            self.treeItems[path] = {}
            for fid, conflict in conflicts.items():
                conflictItem = ConflictItem(path, fid, conflict)
                topItem.addChild(conflictItem)
                self.treeItems[path][fid] = conflictItem

    # user clicked on a cell in the attributes table
    def cellClicked(self, row, col):
        # they clicked on the "merged" column
        if col == 4:
            if self.attributesTable.item(row, col).deleted:
                self.resolveIndividual(self.currentLayer, self.currentPath, None)
                self._afterSolve()
                return
            self.solve() # allow someone to click on the merged column to solve (UX)
            return
        if col > 2:
            return # they didn't click an "intersting" column

        # clicked on a "[deleted]" cell.  Set the resolution to a None (delete)
        if self.attributesTable.item(row,col).deleted:
            self.resolveIndividual(self.currentLayer, self.currentPath, None)
            self._afterSolve()
            return

        conflictItem = self.lastSelectedItem

        attrib = self.attributesTable.item(row, 3).text()
        if attrib not in self.conflicted and attrib not in self.singleChangeProperties:
            return

        item = self.attributesTable.item(row, col)
        value = item.value
        idx = item.idx
        self.attributesTable.setItem(row, 4, ValueItem(value, True, idx,singleModified=attrib in self.singleChangeProperties))
        self.solve()

    def treeItemClicked(self):
        if not self.conflictsTree.selectedItems():
            return
        item = self.conflictsTree.selectedItems()[0]

        if isinstance(item, ConflictItem):
            self.lastSelectedItem = item
            self.currentPath = item.fid
            self.currentLayer = item.path
            self.updateCurrentPath()
            self.solveLocalButton.setEnabled(True)
            self.solveRemoteButton.setEnabled(True)
        else:
            self.attributesTable.setRowCount(0)
            self.solveLocalButton.setEnabled(False)
            self.solveRemoteButton.setEnabled(False)

    def updateCurrentPath(self):
        self.solveLocalButton.setEnabled(False)
        self.solveRemoteButton.setEnabled(False)
        self.showFeatureAttributes()

    def solveAllRemote(self):
        ret = QMessageBox.warning(self, "Solve conflict",
                                "Are you sure you want to solve all conflicts using the '" + self.remoteName + "' version?",
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes)
        if ret == QMessageBox.Yes:            
            self.resolveAll(self.REMOTE)            

    def resolveAll(self, resolutionValue):
        self.resolvedConflicts = {}
        for layername, conflicts in self.conflicts.items():
            layerResolution = {fid:resolutionValue for fid,conflict in conflicts.items()}
            self.resolvedConflicts[layername] = layerResolution

        self._afterSolve()

    def solveAllLocal(self):
        ret = QMessageBox.warning(self, "Solve conflict",
            "Are you sure you want to solve all conflict using the '" + self.localName + "' version?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes);
        if ret == QMessageBox.Yes:
            self.resolveAll(self.LOCAL)

    def _afterSolve(self):
        self.resolvedConflicts = self.asStageable()
        self.okToMerge = (sum([len(d) for d in self.resolvedConflicts.values()]) ==
                          sum([len(d) for d in self.conflicts.values()]))
        self.mergePRButton.setEnabled(self.okToMerge)
        self.treeItemClicked() # set everything up again

    def resolveIndividual(self,layername, fid, resolutionValue):
        layerresolution = self.resolvedConflicts.get(layername, {})
        layerresolution[fid] = resolutionValue
        self.resolvedConflicts[layername] = layerresolution
        self.treeItems[layername][fid].setSolvedIcon()    

    def solveLocal(self):
        self.resolveIndividual(self.currentLayer,self.currentPath, self.LOCAL)
        self._afterSolve()

    def solveRemote(self):
        self.resolveIndividual(self.currentLayer,self.currentPath, self.REMOTE)
        self._afterSolve()

    # stageable - actual features to directly interact with geogig
    # returns a feature or None (for delete)
    # these should be staged to WORK_HEAD then added
    #  the merge should then work
    def asStageable(self):
        stageable = {}
        for layername, resolutions in self.resolvedConflicts.items():
            layerStageable = {} # fid to qgsfeature
            for fid,resolutionValue in resolutions.items():
                if isinstance(resolutionValue, int):
                    if resolutionValue==ConflictDialog.DELETE:
                        layerStageable[fid] = None
                    else:
                        info = self.conflicts[layername][fid]
                        layerStageable[fid] =  self.resolve(info,resolutionValue)
                        # if resolutionValue ==ConflictDialog.LOCAL:
                        #     layerStageable[fid] = info["local"]
                        # if resolutionValue ==ConflictDialog.REMOTE:
                        #     layerStageable[fid] = info["remote"]
                else:
                    layerStageable[fid]= resolutionValue # qgsFeature
            stageable[layername]= layerStageable
        return stageable


    def resolve(self,info,resolutionValue):
        originFeature = info["origin"]
        localFeature = info["local"]
        remoteFeature = info["remote"]
        if resolutionValue == ConflictDialog.LOCAL and localFeature is None:
            return None # resolve to deleted
        if resolutionValue == ConflictDialog.REMOTE and remoteFeature is None:
            return None # resolve to deleted
        if resolutionValue == ConflictDialog.LOCAL and remoteFeature is None:
            return localFeature # remote is deleted, so must be local
        if resolutionValue == ConflictDialog.REMOTE and localFeature is None:
            return remoteFeature  # local is deleted, so must be remote

        # merge - find conflicted values & singleValueChanged values (i.e. attribute only changed in local or remote)
        attribs = [f.name() for f in originFeature.fields().toList()]
        resultAttribs = {}
        for name in attribs:
            values = [originFeature[name],localFeature[name],remoteFeature[name]]
            conflicted = not(values[0] == values[1] or values[1] == values[2] or values[0] == values[2] )
            singleChange = (not conflicted) and (values[0] != values[1] or values[0] != values[2])
            if not singleChange:
                resultAttribs[name] = values[resolutionValue]
            else:
                if values[0] != values[1]:
                    resultAttribs[name] = values[1]
                else:
                    resultAttribs[name] = values[2]

        #geom
        values_geom = [originFeature.geometry(), localFeature.geometry(), remoteFeature.geometry()]
        values = [originFeature.geometry().asWkt(), localFeature.geometry().asWkt(), remoteFeature.geometry().asWkt()]
        conflicted = not (values[0] == values[1] or values[1] == values[2] or values[0] == values[2])
        singleChange = (not conflicted) and (values[0] != values[1] or values[0] != values[2])
        if not singleChange:
            geom =  values_geom[resolutionValue]
        else:
            if values[0] != values[1]:
                geom = values_geom[1]
            else:
                geom = values_geom[2]

        qgisFeature = QgsFeature()
        qgisFeature.setFields(originFeature.fields())
        for key,value in resultAttribs.items():
            qgisFeature[key] = value
        qgisFeature.setGeometry(geom)
        return qgisFeature


    # create the resolved feature
    def solve(self):
        attribs = {}
        for i in range(self.attributesTable.rowCount()):
            item = self.attributesTable.item(i, 4)
            if item.deleted:
                item = self.attributesTable.item(i, 2)
                if item.deleted:
                    value = self.attributesTable.item(i, 1).value
                else:
                    value = item.value
            else:
                value = item.value
            name = self.attributesTable.item(i, 3).text()
            attribs[name] = value
        qgisFeature = QgsFeature()
        fields =  self.lastSelectedItem.conflict["origin"].fields()
        qgisFeature.setFields(fields)
        values = [attribs[field.name()] for field in fields.toList()]
        qgisFeature.setAttributes(values)
        qgisFeature.setGeometry(attribs["geometry"])
        self.resolveIndividual(self.currentLayer,self.currentPath, qgisFeature)
        self._afterSolve()

    # setup the attributes table
    def showFeatureAttributes(self):
        conflictItem = self.lastSelectedItem
        try:
            resolvedFeature = self.resolvedConflicts[conflictItem.path][conflictItem.fid]
        except KeyError:
            # resolvedFeature = conflictItem.conflict["local"]
            resolvedFeature = self.resolve(self.lastSelectedItem.conflict,ConflictDialog.LOCAL)
        self.currentConflictedAttributes = []
        attribs = [f.name() for f in conflictItem.conflict["origin"].fields().toList()]
        attribs.append("geometry")
        self.attributesTable.setRowCount(len(attribs))

        self.conflicted = []
        self.singleChangeProperties = []

        features = [conflictItem.conflict["origin"], conflictItem.conflict["remote"],
                    conflictItem.conflict["local"], resolvedFeature]
        for idx, name in enumerate(attribs):
            font = QFont()
            font.setBold(True)
            font.setWeight(75)
            item = QTableWidgetItem(name)
            item.setFont(font)
            self.attributesTable.setItem(idx, 3, item)
            self.attributesTable.setItem(idx, 4, ValueItem(None, False))

            if name == "geometry": # geometry column
                values = []
                if conflictItem.conflict["origin"] is not None: # be deleted aware
                    values.append(conflictItem.conflict["origin"].geometry())
                else:
                    values.append(None)
                if conflictItem.conflict["remote"] is not None:
                    values.append(conflictItem.conflict["remote"].geometry())
                else:
                    values.append(None)
                if conflictItem.conflict["local"] is not None:
                    values.append(conflictItem.conflict["local"].geometry())
                else:
                    values.append(None)
            else:
                values = []
                if conflictItem.conflict["origin"] is not None:
                    values.append(conflictItem.conflict["origin"][name])
                else:
                    values.append(None)
                if conflictItem.conflict["remote"] is not None:
                    values.append(conflictItem.conflict["remote"][name])
                else:
                    values.append(None)
                if conflictItem.conflict["local"] is not None:
                    values.append(conflictItem.conflict["local"][name])
                else:
                    values.append(None)
            tocompare = []
            if isinstance(values[0], QgsGeometry):
                tocompare = [v.asWkt() if v is not None else None for v in values]
                ok = tocompare[0] == tocompare[1] or tocompare[1] == tocompare[2] or tocompare[0] == tocompare[2]
                singleChange =  ok and (tocompare[0] != tocompare[1] or tocompare[0] != tocompare[2])
            else:                
                ok = values[0] == values[1] or values[1] == values[2] or values[0] == values[2]
                singleChange =  ok and (values[0] != values[1] or values[0] != values[2])

            for i, v in enumerate(values):
                f = features[i]
                geomidx = None
                if name == "geometry" and v is not None:
                    geomidx = tocompare.index(v.asWkt()) + 1
                if f is not None: # be deleted aware
                    self.attributesTable.setItem(idx, i, ValueItem(v, not ok, i + 1,refidx=geomidx,singleModified=singleChange))
                else:
                    self.attributesTable.setItem(idx, i, ValueItem(None, not ok, i + 1, deleted=True,singleModified=singleChange))
            # setup resolved (be deleted aware)
            if name == "geometry":
                v = resolvedFeature.geometry() if resolvedFeature is not None else None                                
                if resolvedFeature is not None:
                    #geomidx = len(tocompare) - tocompare[::-1].index(v.asWkt()) - 1
                    geomidx =   tocompare[::-1].index(v.asWkt()) + 1
                else:
                    geomidx = None
                self.attributesTable.setItem(idx, 4, ValueItem(v, not ok, idx = geomidx, deleted = resolvedFeature is None,singleModified=singleChange))
            else:
                v = resolvedFeature[name] if resolvedFeature is not None else None
                self.attributesTable.setItem(idx, 4, ValueItem(v, not ok, deleted = resolvedFeature is None,singleModified=singleChange))

            if not ok:
                self.conflicted.append(name)
            if singleChange:
                self.singleChangeProperties.append(name)

        self.attributesTable.horizontalHeader().setMinimumSectionSize(100)
        self.attributesTable.horizontalHeader().setStretchLastSection(True)
        self.attributesTable.resizeColumnsToContents()
        header = self.attributesTable.horizontalHeader()
        for column in range(header.count()):
            header.setSectionResizeMode(column, QHeaderView.Fixed)  # can set this to ResizeToContents or Stretch
            width = header.sectionSize(column)
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            header.resizeSection(column, min(150,width))

    def closeEvent(self, evnt):
        if not self.okToMerge:
            ret = QMessageBox.warning(self, "Conflict resolution",                              
                                  "Do you really want to exit and abort the sync operation?",
                                  QMessageBox.Yes | QMessageBox.No)
            if ret == QMessageBox.No:
                evnt.ignore()
            else:
                self.okToMerge = False

class ValueItem(QTableWidgetItem):

    def __init__(self, value, conflicted, idx = None,deleted=False,refidx=None,singleModified=False):
        QTableWidgetItem.__init__(self)
        self.value = value
        self.idx = idx
        self.deleted = deleted
        tooltip = None
        if isinstance(value, QVariant):
            self.value = value.value()
        if value is None:
            s = ""
        if deleted:
            s= "[DELETED]"
        elif isinstance(value, QgsGeometry):
            tooltip = value.asWkt()
            s = tooltip.split("(")[0]
            if refidx is not None:
                s += "[%i]" % refidx
            elif idx is not None:
                s += "[%i]" % idx
        else:
            s = str(value)
        if singleModified:
            self.setBackground(QColor(247,222,149))
        if conflicted:
            self.setBackground(Qt.yellow)
        if deleted:
            self.setBackground(Qt.red)
        self.setText(s)
        self.setFlags(Qt.ItemIsEnabled)
        self.setToolTip(tooltip if tooltip is not None else s)


class ConflictItem(QTreeWidgetItem):

    def __init__(self, path, fid, conflict):
        QTreeWidgetItem.__init__(self)
        self.setText(0, fid)
        self.setIcon(0, unsolvedConflictIcon)
        self.setSizeHint(0, QSize(self.sizeHint(0).width(), 25))
        self.conflict = conflict
        self.fid = fid
        self.path = path

    def setSolvedIcon(self):
        self.setIcon(0, solvedConflictIcon)




