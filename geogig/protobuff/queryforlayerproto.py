import base64
import urllib.request
import gzip
import requests
import time
import json
#import geogig.protobuff.messages_pb2  as messages_pb2
messages_pb2 = None
from qgis.core import QgsMessageLog
from _pyio import BufferedReader
from io import BufferedReader as BufferedReader_io

from geogig.protobuff.debouncingprogressreporter import DebouncingProgressReporter
from geogig.protobuff.featuretype import FeatureTypeHelper
from geogig.protobuff.streamingprotohelper import readSize
from geogig.protobuff.proto2qgis import createQGISFeature, createDiffFeature, createConflictFeature, \
    createQGISFeatureShell, getValue
import concurrent.futures
from queue import Queue
from collections import deque
from qgis.core import QgsMessageLog, QgsFeature, QgsGeometry, QgsVectorLayer
import os

class QueryForLayerProto():
    def __init__(self, connector,progressFn=None):
        self.connector = connector
        self.last_report_time = time.perf_counter()
        self.progressReporter = DebouncingProgressReporter(progressFn)
        self.isCancelled = False

    def querySimple(self,url,query,wrapInMemoryStore=True):
        pwdok, prompted = self.connector.getPassword()
        if pwdok:
            featureTypeHelper, feats = self.queryForFeatures(url,
                                                             query,
                                                             self.connector.user,
                                                             self.connector.password,
                                                             returnAsIterator=False)
            if wrapInMemoryStore:
                return featureTypeHelper.createMemLayer(feats)
            else:
                return feats
        else:
            return QgsVectorLayer("Points?crs=EPSG4326", "dummy", 'memory') #dummy empty layer

    # main function - query GeoGig for data, return a layer with the features
    def query(self, user, repo, layer, refspec, extent=None, screenWidth=None,
              screenHeight=None, limit=None, simplifyGeom=True,
              screenMap_type="WithBBOX",screenMap_factor=1.0, filepath=None, ecqlfilter=None):

        pwdok, prompted = self.connector.getPassword()
        if pwdok:
            query = self.createQuery(refspec, extent, screenWidth,
                  screenHeight, limit, simplifyGeom,
                  screenMap_type=screenMap_type,screenMap_factor=screenMap_factor, ecqlFilter=ecqlfilter)

            # endpoint
            url = QueryForLayerProto.createURL(self.connector, user, repo, layer)
            # get FT and features
            if filepath is None:
                featureTypeHelper, feats = self.queryForFeatures(url, query, self.connector.user,
                                                                      self.connector.password,returnAsIterator=False)
                # create the memory layer
                return featureTypeHelper.createMemLayer(feats)
            else:
                featureTypeHelper, feats = self.queryForFeatures(url, query, self.connector.user,
                                                                 self.connector.password, returnAsIterator=True)

                if os.path.exists(filepath):
                    # featureTypeHelper.createGeopkgLayer(filepath, feats)
                    featureTypeHelper.overwriteGeopkgLayer(filepath, feats,layer)
                else:
                    featureTypeHelper.createGeopkgLayer(filepath, feats)
        else:
            return QgsVectorLayer("Points?crs=EPSG4326", "dummy", 'memory') #dummy empty layer

    @staticmethod
    def createURL(connector,user,repo,layer):
        return "{}layers/{}/{}/{}/rpc/query".format(connector.url, user, repo, layer)

    @staticmethod
    def createURL_PRDIFF(connector, user, repo, layer,prid):
        return "{}repos/{}/{}/pulls/{}/diff/features/{}".format(connector.url, user, repo, prid,layer)

    @staticmethod
    def createQueryFIDs(refspec,geogigids):
        query = {"head": refspec,
                 "filter":{"featureIds": geogigids}
                 }
        return query

    @staticmethod
    def createQuery(refspec, extent=None, screenWidth=None,  screenHeight=None, limit=None, 
                    simplifyGeom=True, screenMap_factor=1.0,screenMap_type="WithBBOX", ecqlFilter=None):
        query = {"head": refspec,
                 "flattenDiffSchema": True}
        if screenMap_factor is None:
            screenMap_factor = 1.0
        if screenMap_type is None:
            screenMap_type = "NONE"

        if screenWidth and screenHeight and screenMap_type != "NONE":
            query["screenWidth"] = screenWidth * screenMap_factor
            query["screenHeight"] = screenHeight * screenMap_factor
        if limit is not None:
            query["limit"] = limit

        if screenMap_type != "NONE":
            query["screenmapReplaceGeom"] = screenMap_type


        if extent is not None and ecqlFilter is not None:
            bboxfilter = 'BBOX("@bounds",{},{},{},{})'\
                            .format(extent[0],extent[1],extent[2],extent[3])
            combinedFilter = "(("+ecqlFilter+") AND (" + bboxfilter + "))"
            query["filter"] = {"cqlFilter":combinedFilter}
        else:
            if extent is not None:
                query["filter"] = {"bbox": extent}

            if ecqlFilter is not None:
                query["filter"] = {"cqlFilter":ecqlFilter}

        if simplifyGeom and extent is not None and screenWidth and screenHeight:
            xextent = extent[2] - extent[0]
            yextent = extent[3] - extent[1]
            query["simplificationDistance"] = min(xextent / float(screenWidth),
                                                  yextent / float(screenHeight)) / 2.0
        return query


    def queryForFeatures(self, url, query, auth_user, auth_pass,returnAsIterator=True):
        # import sys
        # sys.path.append('//Applications//PyCharm.app//Contents//debug-eggs//pycharm-debug.egg')
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        if returnAsIterator:
            return self.queryForFeatures_iterator(url,query,auth_user,auth_pass)
        else:
            return self.queryForFeatures_list(url, query, auth_user, auth_pass)

    # perform actual query against geogig
    def queryForFeatures_iterator(self, url, query, auth_user, auth_pass):
        base64string = base64.b64encode(('%s:%s' % (auth_user, auth_pass)).encode("utf-8")).decode("UTF-8")

        headers = {'Content-Type':'application/json',
                   "Accept": "application/geogig.x-protobuf",
                   "Accept-Encoding": "gzip",
                   "Authorization": "Basic %s" % base64string
                   }
        # QgsMessageLog.logMessage("query - " + json.dumps(query))
        request = urllib.request.Request(url,
                                         data=json.dumps(query).encode('utf8'),
                                         headers=headers,
                                         method="POST")
        gzipReader = None
        underlyingURLReader= urllib.request.urlopen(request)
        bufferedReader = BufferedReader_io(underlyingURLReader, 1024 * 8)
        if underlyingURLReader.headers["Content-Encoding"] == "gzip":
            gzipReader = gzip.GzipFile(fileobj=bufferedReader)
            bufferedReader = BufferedReader_io(gzipReader, 1024 * 8*3)
        if self.isCancelled:
            raise CancelledException("cancelled")

        ftHelper = FeatureTypeHelper(bufferedReader)
        features = self.readFeatures_iterator(bufferedReader,[underlyingURLReader,bufferedReader,gzipReader])

        return ftHelper, features

    def queryForFeatures_list(self, url, query, auth_user, auth_pass):
        #
        # import sys
        # sys.path.append('//Applications//PyCharm.app//Contents//debug-eggs//pycharm-debug.egg')
        # import pydevd
        # pydevd.settrace('localhost', port=65432, stdoutToServer=True, stderrToServer=True,
        #                 trace_only_current_thread=False, overwrite_prev_trace=True, patch_multiprocessing=True,
        #                 suspend=False)
        base64string = base64.b64encode(('%s:%s' % (auth_user, auth_pass)).encode("utf-8")).decode("UTF-8")

        headers = {'Content-Type': 'application/json',
                   "Accept": "application/geogig.x-protobuf",
                   "Accept-Encoding": "gzip",
                   "Authorization": "Basic %s" % base64string
                   }
        # QgsMessageLog.logMessage("query - " + json.dumps(query))
        request = urllib.request.Request(url,
                                         data=json.dumps(query).encode('utf8'),
                                         headers=headers,
                                         method="POST")
        with urllib.request.urlopen(request) as underlyingURLReader:
            try:
                bufferedReader = BufferedReader_io(underlyingURLReader, 1024 * 8 * 3)
                if underlyingURLReader.headers["Content-Encoding"] == "gzip":
                    bufferedReader = gzip.GzipFile(fileobj=bufferedReader)
                    bufferedReader = BufferedReader_io(bufferedReader, 1024 * 8)
                if self.isCancelled:
                    raise CancelledException("cancelled")

                ftHelper = FeatureTypeHelper(bufferedReader)
                features = self.readFeatures_list(bufferedReader)
            finally:
                if bufferedReader is not None:
                    bufferedReader.close()
        return ftHelper, features

    # reads a set of features from the stream and returns
    # them as a list of QgsFeature
    def readFeatures_list(self, raw):
        global messages_pb2
        if messages_pb2 is None:
            import geogig.protobuff.messages_pb2  as messages_pb2
        result = []
        while True:
            if self.isCancelled:
                raw.close()  # close connect -- we will not finish the read
                raise CancelledException("cancelled")
            featureSize = readSize(raw)
            if featureSize == 0:
                return result
            self.progressReporter.reportFeatureRead()

            buff = raw.read(featureSize)
            f = messages_pb2.Feature()
            f.ParseFromString(buff)

            result.append( createQGISFeature(f) )
        return result

    # reads a set of features from the stream and returns
    # them as an Iterator of QgsFeature
    # files = when finished reading, close these (list of .close()-ables)
    def readFeatures_iterator(self, raw,files=None):
        global messages_pb2
        if messages_pb2 is None:
            import geogig.protobuff.messages_pb2  as messages_pb2
        while True:
            if self.isCancelled:
                break
            featureSize = readSize(raw)
            if featureSize == 0:
                break
            self.progressReporter.reportFeatureRead()

            buff = raw.read(featureSize)
            f = messages_pb2.Feature()
            f.ParseFromString(buff)
            yield createQGISFeature(f)

        if files is not None:
            for f in files:
                if f is not None:
                    try:
                        f.close()
                    except:
                        pass
        if self.isCancelled:
            raise CancelledException("cancelled")


    def readDiffFeatures(self, raw, ft):
        global messages_pb2
        if messages_pb2 is None:
            import geogig.protobuff.messages_pb2  as messages_pb2
        while True:
            if self.isCancelled:
                raw.close()  # close connect -- we will not finish the read
                raise CancelledException("cancelled")
            featureSize = readSize(raw)
            if featureSize == 0:
                return
            self.progressReporter.reportFeatureRead()
            buff = raw.read(featureSize)
            f = messages_pb2.Feature()
            f.ParseFromString(buff)
            try:
                yield createDiffFeature(f, ft)
            except StopIteration:
                return                

    def readConflictFeatures(self, raw, ft):
        global messages_pb2
        if messages_pb2 is None:
            import geogig.protobuff.messages_pb2  as messages_pb2
        while True:
            if self.isCancelled:
                raw.close()  # close connect -- we will not finish the read
                raise CancelledException("cancelled")
            featureSize = readSize(raw)
            if featureSize == 0:
                return
            self.progressReporter.reportFeatureRead()
            buff = raw.read(featureSize)
            f = messages_pb2.Feature()
            f.ParseFromString(buff)
            try:
                yield createConflictFeature(f, ft)
            except StopIteration:
                return            


    def queryDiffPR(self, user, repo, layer,prID):
        headers = {"Accept": "application/geogig.x-protobuf",
                   "Accept-Encoding": "gzip"}
        url = self.createURL_PRDIFF(self.connector,user, repo, layer,prID)
        auth_user = self.connector.user
        auth_pass = self.connector.password
        r = requests.get(url,
                          headers=headers, stream=True,
                          auth=(auth_user, auth_pass))
        r.raise_for_status()
        r.raw.decode_content = True
        bufferedReader = BufferedReader(r.raw, 50 * 1024)
        ftHelper = FeatureTypeHelper(bufferedReader)
        fiterator = self.readDiffFeatures(bufferedReader, ftHelper)

        return ftHelper, fiterator



    # returns a list of
    # {
    #  'ID':<geogig ID - string>,
    #  'geogig.changeType':  - int 0=add,1=modify,2=delete,
    #  'old': <QgsFeature> -- old feature (None if add)
    #  'new': <QgsFeature> -- new feature (None if delete)
    # }
    def queryDiff(self, user, repo, layer, refspec, oldRef, featureFilter=None,returnAsIterator=False,
                  oldRefUser=None, oldRefRepoName=None):
        headers = {"Accept": "application/geogig.x-protobuf",
                   "Accept-Encoding": "gzip"}
        query = {"head": refspec,
                 "flattenDiffSchema": False,
                 "oldHead": oldRef}

        if oldRefUser is not None and oldRefRepoName is not None:
            query["oldHeadUser"] = oldRefUser
            query["oldHeadRepo"] = oldRefRepoName

        if featureFilter is not None:
            query["filter"] = featureFilter

        url = QueryForLayerProto.createURL(self.connector, user, repo, layer)
        auth_user = self.connector.user
        auth_pass = self.connector.password
        r = requests.post(url,
                          headers=headers, json=query, stream=True,
                          auth=(auth_user, auth_pass))
        r.raise_for_status()
        r.raw.decode_content = True
        if self.isCancelled:
            r.close()
            raise CancelledException("cancelled")

        bufferedReader = BufferedReader(r.raw, 50 * 1024)
        ftHelper = FeatureTypeHelper(bufferedReader)
        fiterator = self.readDiffFeatures(bufferedReader, ftHelper)

        if returnAsIterator:
            return ftHelper,fiterator
        else:
            return list(fiterator)

        # returns a list of
        # {
        #  'ID':<geogig ID - string>,
        #  'ancestor': <QgsFeature> --   feature
        #  'ours': <QgsFeature> --   feature
        #  'theirs': <QgsFeature> --   feature
        # }

    def queryConflict(self, user, repo, layer, transactionid):
        headers = {"Accept": "application/geogig.x-protobuf",
                   "Accept-Encoding": "gzip",
                   "geogig-transaction-id": transactionid
                   }
        query = {"conflicts":True}


        url = QueryForLayerProto.createURL(self.connector, user, repo, layer)
        auth_user = self.connector.user
        auth_pass = self.connector.password
        r = requests.post(url,
                          headers=headers, json=query, stream=True,
                          auth=(auth_user, auth_pass))
        r.raise_for_status()
        r.raw.decode_content = True
        if self.isCancelled:
            r.close()
            raise CancelledException("cancelled")

        bufferedReader = BufferedReader(r.raw, 50 * 1024)
        ftHelper = FeatureTypeHelper(bufferedReader)
        fiterator = self.readConflictFeatures(bufferedReader, ftHelper)


        return list(fiterator)

    # should send in a bufferedreader
    # this will read to either the end of the stream
    # or, you can segment multiple datasets in the stream
    # by putting a 0 byte in the stream between datasets
    def readFromStream(self,stream):
        ftHelper = FeatureTypeHelper(stream)
        features = self.readFeatures_iterator(stream)
        return ftHelper, features



class CancelledException(Exception):
    pass