from qgis.PyQt.QtCore import QThread, pyqtSignal, QObject
import traceback
import sys
from geogig.protobuff.queryforlayerproto import QueryForLayerProto, CancelledException

class QueryThread(QThread):

    started = pyqtSignal(str,dict) # always paired with a finished (params=url,query)
    finished = pyqtSignal('PyQt_PyObject')
    progress_occurred = pyqtSignal('int')

    def __init__(self,connector):
        QThread.__init__(self)
        self.connector = connector
        self.url = None
        self.query = None
        self.queryForLayerProto = None
        self.nFeaturesReported = 0

    def __del__(self):
        self.wait()

    def abort(self):
        if self.queryForLayerProto is not None:
            self.queryForLayerProto.isCancelled = True

    def createURL(self, user, repo, layer):
        self.url = QueryForLayerProto.createURL(self.connector,user,repo,layer)


    def createQuery(self,refspec, extent=None, screenWidth=None,
              screenHeight=None, limit=None, simplifyGeom=True, screenMap_type="WithBBOX",screenMap_factor=1.0,
              ecqlFilter = None):
        self.query = QueryForLayerProto.createQuery(refspec,extent,screenWidth,screenHeight,
                                             limit,simplifyGeom,screenMap_type=screenMap_type,screenMap_factor=screenMap_factor, ecqlFilter=ecqlFilter)


    def progressMade(self,nfeats):
        nreadBatch = nfeats-self.nFeaturesReported
        self.nFeaturesReported = nfeats
        self.progress_occurred.emit(nreadBatch)

    def run(self):
        self.abort() # this shouldn't do anything since its running on the same thread
        self.queryForLayerProto = QueryForLayerProto(self.connector,self.progressMade)

        if self.url is None:
            raise Exception("QueryThread called without url set")
        if self.query is None:
            raise Exception("QueryThread called without query set")
        try:
            self.started.emit(self.url,self.query)  # alert that a data load has started
            self.nFeaturesReported = 0
            result = self.queryForLayerProto.querySimple(self.url, self.query,wrapInMemoryStore=False)
            cancelled = self.queryForLayerProto.isCancelled
            self.queryForLayerProto = None
            if cancelled:
                self.finished.emit(None)
            else:
                self.finished.emit(result)
        except CancelledException: # not much to do here...
            self.queryForLayerProto = None
            self.finished.emit(None)
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_traceback,
                                      limit=200, file=sys.stdout)
            self.queryForLayerProto = None
            self.finished.emit(None)

