from qgis.PyQt.QtGui import *
from qgis.PyQt.QtWidgets import *
from qgis.PyQt.QtCore import *
from qgis.PyQt.QtSvg import *
import sys
import os
import requests
import json
import math
from functools import partial
from qgis.core import *
from qgis.utils import iface

from qgiscommons2.gui.paramdialog import openParametersDialog, Parameter, STRING, VECTOR, CHOICE

from geogig.gui.historyviewer import HistoryDiffViewerDialog
from geogig.gui.pullrequestsdialog import PullRequestsDialog
from geogig.gui.layerinfodialog import showLayerInfo
from geogig.gui.progressbar import setCurrentWindow, currentWindow
from geogig.geogigwebapi.repomanagement import Repo
from geogig.gui.conflictdialog import ConflictDialog
from geogig.gui.synchronizedialog import SynchronizeDialog

from concurrent.futures import ThreadPoolExecutor
from qgis.PyQt.QtCore import QThread,QObject
from geogig.gui.commitgraph import CommitGraph

from qgis.gui import QgsMessageBar

pluginPath = os.path.split(os.path.dirname(__file__))[0]

def icon(f):
    return QSvgRenderer(os.path.join(pluginPath, "ui", "resources", f))

infoSVGRenderer = icon('info.svg')
downloadSVGRenderer = icon('download.svg')
uploadSVGRenderer = icon('upload.svg')
logSVGRenderer = icon('clock.svg')
forkSVGRenderer = icon('fork.svg')

#https://fontawesome.com/
uploadSVGRenderer = icon('upload.svg')


#https://use.fontawesome.com/releases/v5.0.13/svgs/regular/eye.svg
viewSVGRenderer = icon ('eye.svg')

#https://use.fontawesome.com/releases/v5.0.13/svgs/regular/file-alt.svg
createSVGRenderer = icon('file-alt.svg')

#<div>Icons made by <a href="http://www.freepik.com" title="Freepik">Freepik</a> from <a href="https://www.flaticon.com/" title="Flaticon">www.flaticon.com</a> is licensed by <a href="http://creativecommons.org/licenses/by/3.0/" title="Creative Commons BY 3.0" target="_blank">CC 3.0 BY</a></div>
liveSVGRenderer = icon('liveconnect.svg')

#https://use.fontawesome.com/releases/v5.0.13/svgs/regular/trash-alt.svg
trashSVGRenderer = icon('trash.svg')

BUTTON_SIZE = 16

_style = QgsSettings().value("qgis/style", None) 
isMac =  _style is None and sys.platform == "darwin" or _style is "Macintosh"

class ConstellationViewerDialog(QDialog):

    def __init__(self, server, user, repo):
        QDialog.__init__(self, parent=iface.mainWindow())
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        self.server = server
        self.connector = server.connector
        self.user = user
        self.repo = repo

        self.layout = QVBoxLayout()
        self.layout.setMargin(0)
        self.setLayout(self.layout)

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout.addWidget(self.bar)

        self.view = ConstellationViewerView(self.server, user, repo)
        self.layout.addWidget(self.view)
        self.resize(900, 500)
        self.setWindowTitle("Constellation Viewer [{}/{}]".format(user, repo))
        self.update()
        self.view.adjustSceneToView()

        #setCurrentWindow(self)

        self.setWindowFlags(Qt.Window)

    def closeEvent(self, evt):
        setCurrentWindow()
        if self.view is not None:
            self.view.cleanup()
        evt.accept()

    def messageBar(self):
        return self.bar

        
class ConstellationViewerView(QGraphicsView):

    HSPACING = 20
    VSPACING = 20

    def __init__(self, server, user, repo):
        QGraphicsView.__init__(self)
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        self.server = server 
        self.user = user
        self.repo = repo       
        self.loggedInUser = server.connector.user        
        server.repoForked.connect(self.renderConstellation)
        server.repoDeleted.connect(self.renderConstellation)

        #need to reload everything
        self.server.commitMade.connect(self.fullRefresh)
        self.server.revertDone.connect(self.fullRefresh)
        self.server.resetDone.connect(self.fullRefresh)


        self.server.pullRequestCreated.connect(self.updateAfterPullRequest)
        self.server.pullRequestMerged.connect(self.updateAfterPullRequest)
        self.server.pullRequestClosed.connect(self.updateAfterPullRequest)

        self.server.syncFinished.connect(self.fullRefresh)

        self.repoItems = {}

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        self.renderConstellation()

    # we don't want these signals existing after the window is closed...
    def cleanup(self):
        self.server.repoForked.disconnect(self.renderConstellation)
        self.server.repoDeleted.disconnect(self.renderConstellation)

        # need to reload everything
        self.server.commitMade.disconnect(self.fullRefresh)
        self.server.revertDone.disconnect(self.fullRefresh)
        self.server.resetDone.disconnect(self.fullRefresh)

        self.server.pullRequestCreated.disconnect(self.updateAfterPullRequest)
        self.server.pullRequestMerged.disconnect(self.updateAfterPullRequest)
        self.server.pullRequestClosed.disconnect(self.updateAfterPullRequest)

        self.server.syncFinished.disconnect(self.fullRefresh)

    def fullRefresh(self):
        for key, item in self.repoItems.items():
            if item:
                item.repo.server.resetLogCache()

        self.populateRepoItems() # background fetch

        for item in self.scene.items():
            if isinstance(item, Arrow):
                self.scene.removeItem(item)

        for key, item in self.repoItems.items():
           if item:
               meta =  self.meta[(item.repo.ownerName, item.repo.repoName)]
               item.refresh(meta=meta)

        self.reLayoutItem(self.repoGraphic, 0, 0)

    def updateAfterPullRequest(self, user, repo, pr):
        # need to update everything because a merge causes history changes
        # and the 2 ahead/1 behind to change
        self.fullRefresh()

    def contextMenuEvent(self, event):
        if not isMac:
            menu = QMenu()
            actionFullExtent = QAction("Show full extent", menu)  
            actionFullExtent.triggered.connect(self.showFullExtent)
            menu.addAction(actionFullExtent)

            actionRealSize = QAction("Show real size", menu)  
            actionRealSize.triggered.connect(self.showRealSize)
            menu.addAction(actionRealSize)

            actionRefresh = QAction("Refresh", menu)
            actionRefresh.triggered.connect(self.fullRefresh)
            menu.addAction(actionRefresh)

            menu.exec_(event.globalPos())

    def showRealSize(self):
        self.setTransform(QTransform())

    def showFullExtent(self):
        rect = self.scene.itemsBoundingRect()
        BUFFERSIZE = 40
        bufferedRect = QRectF(rect.x() - BUFFERSIZE, rect.y() - BUFFERSIZE,
                      rect.width() + BUFFERSIZE * 2, rect.height() + BUFFERSIZE * 2)
        self.scene.setSceneRect(bufferedRect)
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.viewport().update()

    def wheelEvent(self, event):
        if event.angleDelta().y() == 0: # not a zoom
            return

        zoomFactor = 1.10

        if event.angleDelta().y() < 0:
            zoomFactor = 1.0/zoomFactor

        visible = self.mapToScene(self.viewport().geometry()).boundingRect()

        # dont allow to zoom out too far
        if visible.contains(self.sceneRect()) and zoomFactor<1.0:
            return
        # dont allow to zoom in too much
        if (visible.width()<200) and zoomFactor > 1.0:
            return

        self.scale(zoomFactor, zoomFactor)

    def populateRepoItems(self):
        self.meta = {}

        with ThreadPoolExecutor(max_workers=6) as executor:
             for repo in self.constellation.all:
                 future = executor.submit(self.popOneRepo,repo)

    def popOneRepo(self,repo):
        layers = repo.server.layers(repo.ownerName, repo.repoName)
        behind, ahead = 0,0
        try:
            parentUser = None
            parentRepo = None
            if repo.forkedFrom is not None:
                parentUser = repo.forkedFrom.ownerName
                parentRepo = repo.forkedFrom.repoName
            behind, ahead = repo.server.compareHistories(repo.ownerName, repo.repoName, parentUser, parentRepo)
        except:
            pass # no info from server
        prs = repo.server.pullRequests(repo.ownerName, repo.repoName)

        self.meta[(repo.ownerName, repo.repoName)] = {
            "layers": layers,
            "behind": behind,
            "ahead": ahead,
            "prs": prs
        }

    def asGraphic2(self,repo):
        root= self.repoItems[(repo.ownerName, repo.repoName)]
        #root = GeoGigRepoItem(repo, self.loggedInUser, self.constellation.repo)
        #self.repoItems[(repo.ownerName, repo.repoName)] = root
        mykids = []
        for child in repo.children:
            mykids.append(self.asGraphic(child))
        root.childRepos = mykids
        return root

    def asGraphic(self,repo):
        meta = self.meta[(repo.ownerName, repo.repoName)]
        root = GeoGigRepoItem(repo, self.loggedInUser, self.constellation.repo, meta=meta)
        self.repoItems[(repo.ownerName, repo.repoName)] = root
        mykids = []
        for child in repo.children:
            mykids.append(self.asGraphic(child))
        root.childRepos = mykids
        return root

    def renderConstellation(self):
        self.scene.clear()
        self.viewport().update()

        self.server.resetLogCache()

        self.constellation = self.server.constellation(self.user, self.repo)

        self.populateRepoItems()
        self.repoGraphic = self.asGraphic(self.constellation.root)
        xoffset = 0
        size = self.layoutItem(self.repoGraphic, xoffset, 0)

        self.adjustSceneToView()

    def adjustSceneToView(self):
        if isMac:
            self.showRealSize()
        else:
            self.showFullExtent()

    def reLayoutItem(self, rootItem, xoff, yoff):
        size = self.sizeRequired(rootItem)
        rootItem.setPos(xoff + size.width() / 2.0 - rootItem.boundingRect().width() / 2.0, yoff)
        #self.scene.addItem(rootItem)
        yoff += rootItem.boundingRect().height() + self.VSPACING
        xoffChild = xoff
        for child in rootItem.childRepos:
            sz = self.reLayoutItem(child, xoffChild, yoff)
            arrow = Arrow(rootItem, child)
            self.scene.addItem(arrow)
            xoffChild += sz.width() + self.HSPACING
        return size

    def layoutItem(self, rootItem, xoff, yoff):
        size = self.sizeRequired(rootItem)
        rootItem.setPos(xoff+size.width()/2.0-rootItem.boundingRect().width()/2.0, yoff)
        self.scene.addItem(rootItem)
        yoff +=  rootItem.boundingRect().height()+ self.VSPACING
        xoffChild = xoff
        for child in rootItem.childRepos:
            sz = self.layoutItem(child, xoffChild, yoff)
            arrow = Arrow(rootItem, child)
            self.scene.addItem(arrow)
            xoffChild += sz.width() + self.HSPACING
        return size

    def sizeRequired(self,repoGraphic):
        if len(repoGraphic.childRepos) ==0:
            return repoGraphic.boundingRect()
        bboxChildren = [self.sizeRequired(item) for item in repoGraphic.childRepos]
        totalWidth = sum([item.width() for item in bboxChildren]) + self.HSPACING * (len(repoGraphic.childRepos) - 1)
        height = max([item.height() for item in bboxChildren])
        return QRectF(-totalWidth/2.0,0,totalWidth,height+repoGraphic.boundingRect().height())

class Arrow(QGraphicsItem):

    ARROW_POINT_SIZE = 7

    def __init__(self, parent, child):
        QGraphicsItem.__init__(self, None)
        self.parent = parent
        self.child = child
        self.setCoords()

    def setCoords(self):
        x1 = self.parent.pos().x() + self.parent.boundingRect().width() / 2
        y1 = self.parent.pos().y() + self.parent.boundingRect().height()
        x2 = self.child.pos().x() + self.child.boundingRect().width() / 2
        y2 = self.child.pos().y() 
        self.sourcePoint = QPointF(x1,y1)
        self.destPoint = QPointF(x2, y2)
        self.line = QLineF(x1,y1,x2,y2)

        angle = math.acos(self.line.dx() / self.line.length())
        if self.line.dy() >= 0:
            angle = 2.0*math.pi - angle

        sourceArrowP1 = self.sourcePoint + QPointF(math.sin(angle + math.pi / 3) * self.ARROW_POINT_SIZE,
                                                   math.cos(angle + math.pi / 3) * self.ARROW_POINT_SIZE)
        sourceArrowP2 = self.sourcePoint + QPointF(math.sin(angle + math.pi - math.pi / 3) * self.ARROW_POINT_SIZE,
                                                   math.cos(angle + math.pi - math.pi / 3) * self.ARROW_POINT_SIZE)

        destArrowP1 = self.destPoint + QPointF(math.sin(angle - math.pi / 3) * self.ARROW_POINT_SIZE,
                                               math.cos(angle - math.pi / 3) * self.ARROW_POINT_SIZE)
        destArrowP2 = self.destPoint + QPointF(math.sin(angle - math.pi + math.pi / 3) * self.ARROW_POINT_SIZE,
                                               math.cos(angle - math.pi + math.pi / 3) * self.ARROW_POINT_SIZE)
        self.arrowTriangle = QPolygonF([self.line.p1(), sourceArrowP1, sourceArrowP2])
        self.bbox = QRectF(self.sourcePoint, self.destPoint).normalized().united(self.arrowTriangle.boundingRect())
 
    def boundingRect(self):
        return self.bbox

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.HighQualityAntialiasing)
        painter.setPen(QPen(Qt.black, 1, Qt.SolidLine, Qt.RoundCap,
                            Qt.RoundJoin))
        painter.drawLine(self.line)
        painter.setBrush(Qt.black)
        painter.drawPolygon(self.arrowTriangle)

class GeoGigRepoItem(QGraphicsObject):

    MIN_WIDTH = 300

    def __init__(self, repo, loggedInUser, originalRepo, parent=None,meta=None):
        QGraphicsObject.__init__(self, parent)
        self.repo = repo
        self.originalRepo = originalRepo
        self.loggedInUser = loggedInUser
        self.belongsToLoggedUser = self.loggedInUser == self.repo.ownerName
        self.isOriginalRepo = repo == originalRepo
        self.childRepos = []
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setContent(meta=meta)

    def mouseDoubleClickEvent(self, event):
        self.scene().views()[0].setTransform(QTransform())
        height = self.boundingRect().height()
        width = self.boundingRect().width()

        rec2 = QRectF(event.scenePos().x()-width*1.5,event.scenePos().y()-height*1.5,
                     width*3,height*3  )
        self.scene().views()[0].fitInView(rec2, Qt.KeepAspectRatio)
        self.scene().views()[0].viewport().update()

    def setContent(self,meta=None):
        title = self.title(self.repo.fullName())
        self.WIDTH = title.boundingRect().width()
        status = self.status(meta)
        layers = self.layers(meta)
        item = SimpleVerticalLayout([title, status, layers], self)
        contentBounds = item.boundingRect()
        self.bounds = QRectF(0, 0, self.WIDTH+10, contentBounds.height() + 10)

    def refresh(self,meta=None):
        for child in self.childItems():
            self.scene().removeItem(child)
        self.setContent(meta=meta)

    def layers(self,meta=None):
        label = QGraphicsTextItem()
        label.setHtml("<b>Layers</b>")
        lines = [label]

        if meta is None:
            layers = self.repo.server.layers(self.repo.ownerName, self.repo.repoName)
        else:
            layers = meta["layers"]
        for layer in layers:
            line = self.layerItem(layer)
            lines.append(line)

        layout = SimpleVerticalLayout(lines, parent=self)
        return layout

    def layerItem(self, layer):
        MAX_WIDTH = self.WIDTH - 102
        line = QGraphicsTextItem()
        text = layer
        line.setHtml(layer)
        width = line.boundingRect().width()
        # if the layer name is too big (and we will truncate), add
        # a tooltip so user can see the full name by hovering on it.
        if width > MAX_WIDTH:
            line.setToolTip(layer)
        while width > MAX_WIDTH:
            text = text[:-1]
            line.setHtml(text)
            width = line.boundingRect().width()
        if text != layer:
            line.setHtml(text + "[...]")

        buttonLog = SVGButton(logSVGRenderer, tooltip="Show history of this layer")
        buttonLog.clicked.connect(partial( self.showLog,layer))        
        buttonInfo = SVGButton(infoSVGRenderer, tooltip="Show detailed info of this layer")
        buttonInfo.clicked.connect(lambda: self.showLayerInfo(layer))
        buttonDownload = SVGButton(downloadSVGRenderer, tooltip="Download this layer and add it to the current project")
        buttonDownload.clicked.connect(lambda: self.addToQgis(layer))
        buttonLive = SVGButton(liveSVGRenderer, tooltip="Add a live connection to this layer to the project")
        buttonLive.clicked.connect(lambda: self.addToQgisLive(layer))

        hlayout = SimpleHorizontalLayout([Spacer(10, 0),
                                          line, buttonInfo, Spacer(2, 0), buttonLog, 
                                          Spacer(2, 0), buttonDownload, Spacer(2, 0), buttonLive, Spacer(10, 0)])

        extraSpace = self.WIDTH - hlayout.boundingRect().width()
        hlayout = SimpleHorizontalLayout([Spacer(10, 0),
                                          line, Spacer(extraSpace,0),
                                          buttonInfo, Spacer(2, 0), buttonLog, Spacer(2, 0), buttonDownload,
                                          Spacer(2, 0), buttonLive])

        return hlayout

    def status(self, meta=None):
        label = QGraphicsTextItem()
        label.setHtml("<b>Status</b>")

        syncLayouts = []
        buttonAhead = SVGButton(createSVGRenderer,tooltip="Create a PR")
        buttonAhead.clicked.connect(self.createPullRequest)
        buttonBehind = SVGButton(downloadSVGRenderer, tooltip="Pull changes from another repo")
        buttonBehind.clicked.connect(self.pullFromAnotherRepo)
        try:
            if meta is None:
                parentUser = None
                parentRepo = None
                if self.repo.forkedFrom is not None:
                    parentUser = self.repo.forkedFrom.ownerName
                    parentRepo = self.repo.forkedFrom.repoName
                behind,ahead = self.repo.server.compareHistories(self.repo.ownerName, self.repo.repoName,
                                                                 parentUser, parentRepo)
            else:
                behind = meta["behind"]
                ahead = meta["ahead"]

            behindLabel = QGraphicsTextItem()
            if behind != 1:
                behindLabel.setHtml("{} commits behind parent".format(behind))
            else:
                behindLabel.setHtml("{} commit behind parent".format(behind))
            if self.belongsToLoggedUser:
                syncLayouts.append(SimpleHorizontalLayout([Spacer(10,0), behindLabel, Spacer(10,0), buttonBehind]))
            else:
                syncLayouts.append(SimpleHorizontalLayout([Spacer(10,0), behindLabel]))
            aheadLabel = QGraphicsTextItem()
            if ahead != 1:
                aheadLabel.setHtml("{} commits ahead of parent".format(ahead))
            else:
                aheadLabel.setHtml("{} commit ahead of parent".format(ahead))
            if self.belongsToLoggedUser:
                syncLayouts.append(SimpleHorizontalLayout([Spacer(10,0), aheadLabel, Spacer(10,0), buttonAhead]))
            else:
                syncLayouts.append(SimpleHorizontalLayout([Spacer(10,0), aheadLabel]))
        except Exception as e:
            syncLabel = QGraphicsTextItem()
            syncLabel.setHtml("Parent not available")
            syncLayouts.append(SimpleHorizontalLayout([Spacer(10,0), syncLabel, Spacer(10,0), buttonAhead, Spacer(2,0), buttonBehind]))

        if meta is None:
            prs = self.repo.server.pullRequests(self.repo.ownerName, self.repo.repoName)
        else:
            prs = meta["prs"]
        if prs:
            prsLabel = QGraphicsTextItem()
            prsLabel.setHtml("{} pull requests".format(len(prs)))
            buttonViewPrs = SVGButton(viewSVGRenderer,tooltip="View PRs")
            buttonViewPrs.clicked.connect(self.viewPullRequests)
            prsLayout = SimpleHorizontalLayout([Spacer(10,0), prsLabel, Spacer(10,0), buttonViewPrs])
        else:
            prsLabel = QGraphicsTextItem()
            prsLabel.setHtml("No pull requests")            
            prsLayout = SimpleHorizontalLayout([Spacer(10,0), prsLabel])

        kids = [label]
        kids.extend(syncLayouts)
        kids.append(prsLayout)
        status = SimpleVerticalLayout(kids, parent=self)
        return status

    def title(self,name):
        buttonLog = SVGButton(logSVGRenderer, tooltip="Show full history of this repository")
        buttonLog.setZValue(2)
        buttonLog.clicked.connect(self.showLog)

        buttonFork = SVGButton(forkSVGRenderer, tooltip="Fork this repository")
        buttonFork.setZValue(2)
        buttonFork.clicked.connect(self.forkRepo)

        extraElements = []
        if self.belongsToLoggedUser:
            buttonTrash = SVGButton(trashSVGRenderer, tooltip="Delete this repository")
            buttonTrash.setZValue(2)
            buttonTrash.clicked.connect(self.deleteRepo)
            extraElements = [buttonFork,Spacer(2, 0), buttonTrash]

        label = QGraphicsTextItem()
        label.setHtml("<b>"+name+"</b>")
        layoutElements = [label, Spacer(5, 0), buttonLog, Spacer(2, 0), buttonFork]
        layoutElements.extend(extraElements)
        title = SimpleHorizontalLayout(layoutElements)
        if title.boundingRect().width() < self.MIN_WIDTH:
            extra = self. MIN_WIDTH - title.boundingRect().width()
            layoutElements = [label, Spacer(extra,0),Spacer(5,0), buttonLog, Spacer(2, 0), buttonFork]
            layoutElements.extend(extraElements)
            title = SimpleHorizontalLayout(layoutElements, parent=self)
        return title

    def boundingRect(self):
        return self.bounds

    def paint(self, painter, option, widget):
        painter.setBrush(QColor(235, 235, 235))
        if self.belongsToLoggedUser:
            pen = QPen(QColor(100, 235, 100))
            pen.setWidthF(3)
            painter.setPen(pen)
        if self.isOriginalRepo:
            pen = QPen(QColor(235, 100, 100))
            pen.setWidthF(5)
            painter.setPen(pen)
        painter.drawRect(self.boundingRect())


    def pullFromAnotherRepo(self):
        if self.repo.forkedFrom is not None:
            upstreamUser = self.repo.forkedFrom.ownerName
            upstreamRepoName = self.repo.forkedFrom.repoName
        else:
            upstreamUser = None
            upstreamRepoName = None
        syncDialog = SynchronizeDialog(self.repo.ownerName, self.repo.repoName, self.repo.server, 
                                        upstreamUser, upstreamRepoName)
        syncDialog.exec_()

    def createPullRequest(self):
        defaultParent = None
        if self.repo.forkedFrom is not None:
            defaultParent = self.repo.forkedFrom.ownerName + ":" + self.repo.forkedFrom.repoName
        dlg = PullRequestsDialog(self.repo.server, self.repo.ownerName, self.repo.repoName, True,
                                 defaultParent=defaultParent)
        dlg.exec_()

    def viewPullRequests(self):
        dlg = PullRequestsDialog(self.repo.server, self.repo.ownerName, self.repo.repoName, False)
        dlg.exec_()

    def showLayerInfo(self,layer=None):
        showLayerInfo(self.repo.server, self.repo.ownerName, self.repo.repoName, layer)
        
    def showLog(self, layer=None):
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        #currentWindow().showMinimized()
        if layer is None:
            commits, commitsDict = self.repo.server.log(self.repo.ownerName, self.repo.repoName, "master")
            graph = CommitGraph(commits, commitsDict)
        else:
            commitsAll, commitsDictAll, commitsLayer, commitsDictLayer = self.repo.server.logAll(self.repo.ownerName, self.repo.repoName, "master", layer)
            graph = CommitGraph(commitsAll, commitsDictAll, commitsLayer)
        dialog = HistoryDiffViewerDialog(self.repo.server, self.repo.ownerName, self.repo.repoName, graph)
        dialog.exec_()

    def addToQgis(self, layer):
        commitid = self.repo.server.commitidForBranch(self.repo.ownerName, self.repo.repoName, "master")
        from geogig.layers import addGeogigLayer
        added = addGeogigLayer(self.repo.server, self.repo.ownerName, self.repo.repoName, layer, 
                                commitid, False, currentWindow())

    def addToQgisLive(self, layer):
        from geogig.layers import addGeogigLayer
        addGeogigLayer(self.repo.server, self.repo.ownerName, self.repo.repoName, layer, "HEAD", True)
        self.showLayerAddedMessage() 

    def showLayerAddedMessage(self):
        self._parentView().parent().messageBar().pushMessage(
                                "Layer", "Layer was correctly added to QGIS project",
                                level=Qgis.Info, duration=5)
    def _parentView(self):
        return self.scene().views()[0]

    def forkRepo(self):
        name = self.repo.repoName if not self.loggedInUser == self.repo.ownerName else self.repo.repoName + "_2"
        newRepoName, okPressed = QInputDialog.getText(self._parentView().parent(), "Fork repo", 
                                                    "Name for forked repo:", text=name)
        if okPressed:
            self.repo.forkRepo(newRepoName)

    def deleteRepo(self):
        ret = QMessageBox.critical(self._parentView().parent(),
                                    "Delete repository",
                                    "Are you sure you want to delete this repository?",
                                    QMessageBox.Ok | QMessageBox.Cancel)
        if ret == QMessageBox.Ok:
            self.repo.delete()

class SimpleVerticalLayout(QGraphicsObject):

    def __init__(self, kids, parent=None, buffer=-4):
        QGraphicsObject.__init__(self,parent)
        self.kids = kids
        height = sum([item.boundingRect().height() for item in self.kids]) + buffer*len(kids)
        width = max([item.boundingRect().width() for item in self.kids])
        yoff = 0
        for kid in self.kids:
            kid.setParentItem(self)
            kid.setPos(0, yoff)
            yoff += kid.boundingRect().height() + buffer
        self.bounds = QRectF(0, 0, width, height)

    def boundingRect(self):
        return self.bounds

    def paint(self, painter, option, widget):
        pass

class SimpleHorizontalLayout(QGraphicsObject):

    def __init__(self, kids, parent=None,buffer=0):
        QGraphicsObject.__init__(self,parent)
        self.kids = kids
        height =  max([item.boundingRect().height() for item in self.kids])
        width  =  sum([item.boundingRect().width() for item in self.kids]) + buffer*len(kids)
        xoff = 0
        for kid in self.kids:
            kid.setParentItem(self)
            yoffset = (height-kid.boundingRect().height())/2.0
            kid.setPos(xoff,yoffset)
            xoff += kid.boundingRect().width()+buffer
        self.bounds = QRectF(0,0,width,height)

    def boundingRect(self):
        return self.bounds

    def paint(self, painter, option, widget):
        pass

class Spacer(QGraphicsItem):
    def __init__(self, width,height,  parent=None ):
        QGraphicsItem.__init__(self, parent)
        self.bounds = QRectF(0,0,width,height)

    def boundingRect(self):
        return self.bounds

    def paint(self, painter, option, widget):
        pass

class SVGButton(QGraphicsObject):

    clicked = pyqtSignal()

    def __init__(self,renderer, parent=None, size=BUTTON_SIZE, tooltip=None):
        QGraphicsObject.__init__(self,parent)
        self.renderer = renderer
        self.size = size
        self.setAcceptHoverEvents(True)
        self.isHover = False
        if tooltip is not None:
            self.setToolTip(tooltip)

    def mousePressEvent(self,evt):
        self.clicked.emit()

    def boundingRect(self):
        return QRectF(0, 0, self.size, self.size)

    def hoverEnterEvent(self, qGraphicsSceneHoverEvent):
        self.isHover = True
        QApplication.setOverrideCursor(QCursor(Qt.ArrowCursor))
        self.update()

    def hoverLeaveEvent(self, qGraphicsSceneHoverEvent):
        self.isHover = False
        QApplication.restoreOverrideCursor()
        self.update()

    def paint(self, painter, option, widget):
        if self.isHover:
            pen = QPen(QColor(100, 100, 100))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(QColor(200,200,200))
        else:
            pen = QPen(QColor(0, 0, 0))
            painter.setPen(pen)

        painter.drawRect(self.boundingRect())
        rect = QRectF(1,1,self.size-2,self.size-2)
        self.renderer.render(painter,rect)
