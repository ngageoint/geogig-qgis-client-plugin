# -*- coding: utf-8 -*-

from builtins import str
from builtins import range

import os
import sys

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QDateTime, QDate, QTime
from qgis.PyQt.QtGui import QIcon, QColor, QBrush
from qgis.PyQt.QtWidgets import (QHBoxLayout,
                                 QVBoxLayout,
                                 QTableWidgetItem,
                                 QWidget,
                                 QPushButton,
                                 QLabel,
                                 QHeaderView,
                                 QTreeWidgetItem,
                                 QDialog, QTreeWidgetItemIterator
                                )
from qgis.core import QgsGeometry, QgsCoordinateReferenceSystem, QgsWkbTypes

from qgiscommons2.gui import execute

ADDED, MODIFIED, REMOVED, UNCHANGED = 0, 1, 2, 3

pluginPath = os.path.split(os.path.dirname(__file__))[0]

def icon(f):
    return QIcon(os.path.join(pluginPath, "ui", "resources", f))

layerIcon = icon( "layer_group.svg")
featureIcon = icon("geometry.png")
addedIcon = icon("added.png")
removedIcon = icon("removed.png")
modifiedIcon = icon("modified.gif")

sys.path.append(os.path.dirname(__file__))
pluginPath = os.path.split(os.path.dirname(__file__))[0]
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'ui', 'diffviewerwidget.ui'))

class DiffViewerDialog(QDialog):
    def __init__(self, changes):
        super(QDialog, self).__init__()
        widget = DiffViewerWidget(changes)
        layout = QVBoxLayout()
        layout.setMargin(0)
        layout.addWidget(widget)
        self.setLayout(layout)
        self.setFixedSize(1024, 768)
    

class DiffViewerWidget(WIDGET, BASE):

    def __init__(self, changes):
        super(DiffViewerWidget, self).__init__()
        self.changes = changes

        self.setupUi(self)

        self.setWindowFlags(self.windowFlags() |
                            Qt.WindowSystemMenuHint)

        self.featuresTree.currentItemChanged.connect(self.treeItemChanged)

        self.featuresTree.header().hide()

        self.fillTree()

    def setChanges(self, changes):
        self.changes = changes
        self.attributesTable.clear()
        self.fillTree()
        self.selectFirstChangedFeature()

    def selectFirstChangedFeature(self):
        iterator = QTreeWidgetItemIterator(self.featuresTree)
        while iterator.value():
            item = iterator.value()
            if isinstance(item,FeatureItem):
                self.featuresTree.setCurrentItem(item)
                return
            iterator += 1

    def treeItemChanged(self, current, previous):
        if not isinstance(current, FeatureItem):
            self.attributesTable.clear()
            self.attributesTable.setHorizontalHeaderLabels(["Old value", "New value", "Change type"])
            self.attributesTable.setRowCount(0)
            return
        new = current.new
        old = current.old
        reference = new or old
        changeTypeColor = [Qt.green, QColor(255, 170, 0), Qt.red, Qt.white]                
        changeTypeName = ["Added", "Modified", "Removed", "Unchanged"]
        self.attributesTable.clear()
        self.attributesTable.verticalHeader().show()
        self.attributesTable.horizontalHeader().show()
        self.attributesTable.setRowCount(len(reference.fields().toList()) + 1)
        fields = [f.name() for f in reference.fields().toList()]
        labels = fields + ["geometry"]
        self.attributesTable.setVerticalHeaderLabels(labels)
        self.attributesTable.setHorizontalHeaderLabels(["Old value", "New value", "Change type"])
        for i, attrib in enumerate(fields):
            try:                
                if old is None:                    
                    newvalue = new[attrib]
                    oldvalue = ""
                    changeType = ADDED
                elif new is None:
                    oldvalue = old[attrib]
                    newvalue = ""
                    changeType = REMOVED
                else:
                    oldvalue = old[attrib]
                    newvalue = new[attrib]
                    if oldvalue != newvalue:
                        changeType = MODIFIED
                    else:
                        changeType = UNCHANGED                    
            except:
                oldvalue = newvalue = ""
                changeType = UNCHANGED

            self.attributesTable.setItem(i, 0, DiffItem(oldvalue))
            self.attributesTable.setItem(i, 1, DiffItem(newvalue))
            self.attributesTable.setItem(i, 2, DiffItem(changeTypeName[changeType]))
            for col in range(3):
                self.attributesTable.item(i, col).setBackground(QBrush(changeTypeColor[changeType]));

        row = len(reference.fields().toList())     
        if old is None:
            newvalue = QgsWkbTypes.displayString(new.geometry().wkbType()) if new.geometry() is not None else ""
            newvalue_tooltip = new.geometry().asWkt() if new.geometry() is not None else None
            oldvalue = ""
            oldvalue_tooltip = None
            changeType = ADDED
        elif new is None:
            oldvalue = QgsWkbTypes.displayString(old.geometry().wkbType()) if old.geometry() else ""
            oldvalue_tooltip = old.geometry().asWkt() if old.geometry() is not None else None
            newvalue = ""
            newvalue_tooltip = None
            changeType = REMOVED
        else:
            oldvalue = QgsWkbTypes.displayString(old.geometry().wkbType()) if old.geometry() else ""
            newvalue_tooltip = new.geometry().asWkt() if new.geometry() is not None else None
            oldvalue_tooltip = old.geometry().asWkt() if old.geometry() is not None else None
            newvalue = QgsWkbTypes.displayString(new.geometry().wkbType()) if new.geometry() else ""
            if old.geometry().asWkt() != new.geometry().asWkt():
                changeType = MODIFIED
            else:
                changeType = UNCHANGED            
        self.attributesTable.setItem(row, 0, DiffItem(oldvalue,tooltip=oldvalue_tooltip))
        self.attributesTable.setItem(row, 1, DiffItem(newvalue,tooltip=newvalue_tooltip))
        self.attributesTable.setItem(row, 2, DiffItem(changeTypeName[changeType]))
        
        for col in range(3):
            try:
                self.attributesTable.item(row, col).setBackground(QBrush(changeTypeColor[changeType]));
            except:
                pass

        self.attributesTable.horizontalHeader().setMinimumSectionSize(88)
        self.attributesTable.resizeColumnsToContents()
        header = self.attributesTable.horizontalHeader()
        for column in range(header.count()):
            header.setSectionResizeMode(column, QHeaderView.Fixed)  # can set this to ResizeToContents or Stretch
            width = header.sectionSize(column)
            header.resizeSection(column, width)
            header.setSectionResizeMode(column, QHeaderView.Interactive)


    def fillTree(self):
        self.featuresTree.clear()
        for layer, changes in self.changes.items():
            layerItem = QTreeWidgetItem()
            layerItem.setText(0, layer)
            layerItem.setIcon(0, layerIcon)
            self.featuresTree.addTopLevelItem(layerItem)
            addedItem = QTreeWidgetItem()
            addedItem.setText(0, "Added")
            addedItem.setIcon(0, addedIcon)
            layerItem.addChild(addedItem)
            removedItem = QTreeWidgetItem()
            removedItem.setText(0, "Removed")
            removedItem.setIcon(0, removedIcon)
            layerItem.addChild(removedItem)
            modifiedItem = QTreeWidgetItem()
            modifiedItem.setText(0, "Modified")
            modifiedItem.setIcon(0, modifiedIcon)
            layerItem.addChild(modifiedItem)
            subItems=[addedItem, modifiedItem, removedItem]

            for f in changes:
                new = f["new"]
                old = f["old"]
                item = FeatureItem(f["ID"], old, new)
                subItems[f["geogig.changeType"]].addChild(item)

        self.attributesTable.clear()
        self.attributesTable.verticalHeader().hide()
        self.attributesTable.horizontalHeader().hide()

        self.featuresTree.expandAll()

class FeatureItem(QTreeWidgetItem):
    def __init__(self, fid, old, new):
        QTreeWidgetItem.__init__(self)
        self.setIcon(0, featureIcon)        
        self.setText(0, fid)
        self.old = old
        self.new = new

class DiffItem(QTableWidgetItem):

    def __init__(self, value,tooltip=None):
        self.value = value
        if value is None:
            s = ""
        else:
            if isinstance(value,QDateTime) or isinstance(value,QDate) or isinstance(value,QTime):
                s= value.toString(Qt.ISODate)
            else:
                s = str(value)
        QTableWidgetItem.__init__(self, s)
        if tooltip is not None:
            self.setToolTip(str(tooltip))
        else:
            self.setToolTip(s)
