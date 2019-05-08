import os
import sqlite3
import string

from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry,QgsFeatureRequest, QgsExpression
import sip
from geogig.utils import GEOGIGID_FIELD, replaceFeatureInLayer, addFeatureToLayer, getFeatureFromGeogigId, \
    addFeaturesToLayer, getFeaturesFromGeogigIds, replaceFeaturesInLayer


# audit
#  * geogig_deleted_rows  (copy of the deleted row)
#  * geogig_inserted_rows    (fid of added rows)
#  * geogig_updated_rows_orig (ORIG copy of the updated row)
#           *** if row updated more than once, only the original data is in this table
#
#  DB actions -
#    row deleted -> copy OLD to geogig_deleted_rows
#    update row -> if the FID does not existing in geogig_updated_rows_orig, then copy OLD to it
#    add row -> copy fid to geogig_inserted_rows
#
# special situations -
#    * delete a modified row
#    * add and update a row
#    * multiple updates of row
#    * add then delete
#    * add then update then delete
#
#########################################################################
#
# getting change set
#
#
#########################################################################
#
# reverting to base revision
#
#

class SqliteCursor:
    def setupCursor(self):
        #r = self.cursor.execute("PRAGMA journal_mode=WAL").fetchone()
        pass

    def __init__(self, fname):
        self.conn = sqlite3.connect(fname)
        self.cursor = self.conn.cursor()
        self.setupCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cursor.close()
        self.conn.commit()
        self.conn.close()


METADATA_TABLE = "geogig_layer_metadata"

def setMetadataValue(fname, key, value):
    layerMetadata = QgsVectorLayer(fname + "|layername="+METADATA_TABLE)
    features = list(layerMetadata.getFeatures(QgsFeatureRequest(
        QgsExpression('"key"=\'{}\''.format( key)))))
    if len(features) == 1:
        # replace
        attrs = {}
        attrs[0] = features[0].attributes()[0] # this will be the id/fid
        attrs[1] = key
        attrs[2] = value
        r = layerMetadata.dataProvider().changeAttributeValues({features[0].id(): attrs})
    else:
        #insert
        f = QgsFeature()
        f.setAttributes([None,key,value])
        r =layerMetadata.dataProvider().addFeatures([f])

    sip.delete(layerMetadata)
    del layerMetadata


def getMetadataValue(fname, key):
    layerMetadata = QgsVectorLayer(fname + "|layername=" + METADATA_TABLE)
    features = list(layerMetadata.getFeatures(QgsFeatureRequest(
        QgsExpression('"key"=\'{}\''.format(key)))))
    if len(features) == 1:
        r = features[0]["value"]
    else:
        r = None

    sip.delete(layerMetadata)
    del layerMetadata
    return r


# tname is layername
def dropTable(fname,tname):
    with SqliteCursor(fname) as conn:
        r = conn.cursor.execute("DROP TABLE   {tn}".format(tn=tname))
        r = conn.cursor.execute("drop table   rtree_{tn}_geom".format(tn=tname))
        r = conn.cursor.execute("delete from  gpkg_contents where table_name=?", (tname,))
        r = conn.cursor.execute("delete from  gpkg_extensions where table_name=?", (tname,))
        r = conn.cursor.execute("delete from  gpkg_geometry_columns where table_name=?", (tname,))
        r = conn.cursor.execute("delete from  gpkg_ogr_contents where table_name=?", (tname,))

        # deleted when table is deleted
        # r = conn.cursor.execute("DROP TRIGGER geogig_row_delete")
        # r = conn.cursor.execute("DROP TRIGGER geogig_row_insert")
        # r = conn.cursor.execute("DROP TRIGGER geogig_row_update")

        r = conn.cursor.execute("delete from  gpkg_contents where table_name='geogig_deleted_rows' ")
        r = conn.cursor.execute("delete from  gpkg_extensions where table_name='geogig_deleted_rows'" )
        r = conn.cursor.execute("delete from  gpkg_geometry_columns where table_name='geogig_deleted_rows'")

        r = conn.cursor.execute("delete from  gpkg_contents where table_name='geogig_updated_rows_orig' ")
        r = conn.cursor.execute("delete from  gpkg_extensions where table_name='geogig_updated_rows_orig'")
        r = conn.cursor.execute("delete from  gpkg_geometry_columns where table_name='geogig_updated_rows_orig'")


        r = conn.cursor.execute("DROP TABLE   geogig_deleted_rows")
        r = conn.cursor.execute("DROP TABLE   geogig_updated_rows_orig")
        r = conn.cursor.execute("DROP TABLE   geogig_inserted_rows")


def addAuditTables(fname):
    dataTable = getDataTableName(fname)
    cols = getColumnMeta(fname,dataTable)
    createCols = "(" + ",".join(['"'+c[1] + '"' + " " + c[2] for c in cols])+", PRIMARY KEY (fid))"
    # createCols = "(" + ",".join([ c[1] + " " + c[2] for c in cols]) + ", PRIMARY KEY (fid))"

    with SqliteCursor(fname) as conn:
        r = conn.cursor.execute("CREATE TABLE {tn} (fid integer primary key autoincrement not null, key TEXT NOT NULL, value TEXT NOT NULL)"
                  .format(tn=METADATA_TABLE))
        r = conn.cursor.execute("CREATE TABLE geogig_deleted_rows  {cols}"
                  .format(cols=createCols))
        r = conn.cursor.execute("CREATE TABLE geogig_inserted_rows (fid integer primary key not null)")
        r = conn.cursor.execute("CREATE TABLE geogig_updated_rows_orig {cols}"
                  .format(cols=createCols))

        r = conn.cursor.execute("CREATE unique INDEX idx_geogig_updated_rows_orig ON geogig_updated_rows_orig (fid)")
        # this helps when getting change sets from the DB
        r = conn.cursor.execute("CREATE INDEX idx_geogigid ON \"{}\" ({})".format(dataTable,GEOGIGID_FIELD))

        addTriggers(conn.cursor, dataTable, cols)
        registerAuditAsLayer(conn.cursor, dataTable)


def registerAuditAsLayer(c,dataTable):
    c.execute("""
              INSERT INTO gpkg_contents 
                  SELECT 'geogig_deleted_rows',data_type,'geogig_deleted_rows',description,last_change, min_x,min_y,max_x,max_y,srs_id 
                  FROM  gpkg_contents
                  WHERE table_name = ?""",(dataTable,))
    c.execute("""
              INSERT INTO gpkg_geometry_columns
                  SELECT 'geogig_deleted_rows',column_name,geometry_type_name,srs_id,z,m
                  FROM  gpkg_geometry_columns
                  WHERE table_name = ?""",(dataTable,))

    c.execute("""
             INSERT INTO gpkg_contents 
                 SELECT 'geogig_updated_rows_orig',data_type,'geogig_updated_rows_orig',description,last_change, min_x,min_y,max_x,max_y,srs_id 
                 FROM  gpkg_contents
                 WHERE table_name = ?""",(dataTable,))
    c.execute("""
             INSERT INTO gpkg_geometry_columns
                 SELECT 'geogig_updated_rows_orig',column_name,geometry_type_name,srs_id,z,m
                 FROM  gpkg_geometry_columns
                 WHERE table_name = ?""",(dataTable,))

def addTriggers(c,dataTableName,cols):
    colNames_old = ",".join(["old."+'"'+c[1]+'"' for c in cols])
    simpleCols = ",".join(['"'+c[1]+'"' for c in cols])
    # colNames_old = ",".join(["old."+c[1] for c in cols])
    # simpleCols = ",".join([c[1] for c in cols])

    c.execute("""CREATE TRIGGER geogig_row_delete AFTER DELETE ON "{tn}" 
                            BEGIN 
                               INSERT INTO geogig_deleted_rows ({simple_cols}) VALUES ({cols});
                            END
                         """.format(tn=dataTableName, cols=colNames_old, simple_cols=simpleCols))

    c.execute("""CREATE TRIGGER geogig_row_insert AFTER INSERT ON "{tn}" 
                            BEGIN 
                               INSERT INTO geogig_inserted_rows (fid) VALUES (NEW.FID);
                            END
                         """.format(tn=dataTableName))

    c.execute("""CREATE TRIGGER geogig_row_update AFTER UPDATE ON "{tn}" 
                            BEGIN 
                               INSERT OR IGNORE INTO geogig_updated_rows_orig ({simple_cols}) VALUES ({cols});
                            END
                         """.format(tn=dataTableName, cols=colNames_old, simple_cols=simpleCols))

def dropTriggers(c):
    c.execute("DROP TRIGGER geogig_row_delete")
    c.execute("DROP TRIGGER geogig_row_insert")
    c.execute("DROP TRIGGER geogig_row_update")




def getDataTableName(fname):
    with SqliteCursor(fname) as conn:
        conn.cursor.execute("SELECT table_name FROM gpkg_geometry_columns WHERE table_name NOT LIKE 'geogig_%'")
        r = conn.cursor.fetchone()[0]
        return cleanseSqliteTableName(r)

def cleanseSqliteTableName(tname):
    whitelist = string.ascii_letters + string.digits + '_'
    cleansedTname = ''.join(c for c in tname if c in whitelist)
    if tname != cleansedTname:
        raise Exception("bad table name: "+tname)
    if tname.lower().startswith("sqlite_"):
        raise Exception("bad table name: " + tname)
    return cleansedTname

def getColumnMeta(fname, tname):
    with SqliteCursor(fname) as conn:
        r = conn.cursor.execute("PRAGMA TABLE_INFO ('{tn}')".format(tn=tname)).fetchall()
        return r




# this is overly complex because we have to use  QgsVectorLayer only
# to access the features.
# 1. remove triggers (don't want to record what we are doing) - sqlite
# 2. determine what needs to be deleted/inserted -sqlite
# 3. do feature deletion and and moving - QgsVectorLayer
# 4. delete all the info in the audit tables (we are fresh) - sqlite
# 5. put back triggers - sqlite
#
# NOTE: we can NOT do a transaction because we are using sqlite and QgsVectorLayer

def revertToBaseRevision(fname, layername):
    actions = determineRevertActions(fname)
    revertFeatures(fname, actions,layername)
    clearAuditTables(fname)


def revertFeatures(fname,actions,layername):
    layerDeletes = QgsVectorLayer(fname+"|layername=geogig_deleted_rows")
    request = QgsFeatureRequest()
    request.setFilterFids(actions["addDeleted"])
    featuresToInsert1 = list(layerDeletes.getFeatures(request))
    sip.delete(layerDeletes)
    del layerDeletes


    layerUpdates = QgsVectorLayer(fname + "|layername=geogig_updated_rows_orig")
    request = QgsFeatureRequest()
    request.setFilterFids(actions["addUpdated"])
    featuresToInsert2 = list(layerUpdates.getFeatures(request))
    sip.delete(layerUpdates)
    del layerUpdates

    # do delete
    layer = QgsVectorLayer(fname + "|layername="+layername)
    provider = layer.dataProvider()

    r=provider.deleteFeatures(actions["delete"])
    r=provider.addFeatures(featuresToInsert1)
    r=provider.addFeatures(featuresToInsert2)

    sip.delete(layer)
    del layer


def union(list1,list2):
    s1 = set(list1)
    s2 = set(list2)
    return list(s1.union(s2))

def difference(list1,list2):
    s1 = set(list1)
    s2 = set(list2)
    return list(s1.difference(s2))



# determine what needs to be modified
# {
#   "delete": List of int (FIDs)
#   "addDeleted": List of int (FIDs) for features from geogig_deleted_rows
#   "addUpdated": List of int (FIDs) for features from geogig_updated_rows_orig
# }
# so, to execute...
# a) delete everything in the datatable with FIDs in "delete"
# b) get the features from geogig_deleted_rows and put in the datatable
# c) get the features from geogig_updated_rows_orig and put in the datatable
#
# delete --> everything added or modified
# addDeleted --> this will be all the features in geogig_deleted_rows
#                  EXCEPT
#                        * ones also in geogig_updated_rows_orig (rep a modified and deleted features - use the modified orig version)
#                        * ones in geogig_inserted_rows (these are new, don't re-add)
#
# addUpdated -->  this will be all the features in geogig_inserted_rows
#                  EXCEPT
#                       * ones in geogig_inserted_rows (these are new)
#
def determineRevertActions(fname):
    layerDeletes = QgsVectorLayer(fname + "|layername=geogig_deleted_rows")
    layerDeletes_fts = list(layerDeletes.getFeatures())
    layerDeletes_fids = [f["fid"] for f in layerDeletes_fts]

    sip.delete(layerDeletes)
    del layerDeletes

    layerUpdates = QgsVectorLayer(fname + "|layername=geogig_updated_rows_orig")
    layerUpdates_fts = list(layerUpdates.getFeatures())
    layerUpdates_fids = [f["fid"] for f in layerUpdates_fts]

    sip.delete(layerUpdates)
    del layerUpdates

    layerAdds = QgsVectorLayer(fname + "|layername=geogig_inserted_rows")
    layerAdds_fts = list(layerAdds.getFeatures())
    layerAdds_fids = [f["fid"] for f in layerAdds_fts]

    sip.delete(layerAdds)
    del layerAdds

    deletes = union(layerAdds_fids,layerUpdates_fids)
    xfer_deleted = difference(layerDeletes_fids, union(layerUpdates_fids,layerAdds_fids))
    xfer_updated = difference(layerUpdates_fids,layerAdds_fids)

    result = {
        "delete":deletes,
        "addDeleted" :xfer_deleted,
        "addUpdated" : xfer_updated
    }
    return result

# from geogig.geopkg_tools import GeoPKGHelper
# fname = ﻿'/Users/dblasby/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/_test.gpkg'
# a= getChangeSet(fname)

# returns a list of
# {
#  'ID':<geogig ID - string>,
#  'geogig.changeType':  - int 0=add,1=modify,2=delete,
#  'old': <QgsFeature> -- old feature (None if add)
#  'new': <QgsFeature> -- new feature (None if delete)
# }
def getChangeSet(fname):
    raw = getChangeSetRaw(fname)

    layer = QgsVectorLayer(fname)

    request = QgsFeatureRequest()
    request.setFilterFids(raw["inserted_fids"])
    features_inserted = layer.getFeatures(request)

    request = QgsFeatureRequest()
    request.setFilterFids(raw["updated_fids"])
    features_updated = list(layer.getFeatures(request))

    origLayer = QgsVectorLayer(fname + "|layername=geogig_updated_rows_orig")
    layerDeletes = QgsVectorLayer(fname+"|layername=geogig_deleted_rows")

    result = []


    deleted_features = getFeaturesFromGeogigIds(raw["deleted_geogigids"],layerDeletes)
    for geogigid in raw["deleted_geogigids"]:
        result.append({"ID": geogigid,
                        "old": deleted_features[geogigid],
                        "new": None,
                        "geogig.changeType": 2})
    for newFeature in features_inserted:
        result.append({"ID": newFeature[GEOGIGID_FIELD],
                        "old": None,
                        "new": newFeature,
                        "geogig.changeType": 0})

    origFeatures = getFeaturesFromGeogigIds([f[GEOGIGID_FIELD] for f in features_updated],origLayer)
    for newFeature in features_updated:
        id = newFeature[GEOGIGID_FIELD]
        result.append({"ID": id,
                        # "old": _getOldFeature(newFeature[GEOGIGID_FIELD], origLayer),
                        "old": origFeatures[id] ,
                        "new": newFeature,
                        "geogig.changeType": 1})
    sip.delete(layer)
    del layer
    sip.delete(origLayer)
    del origLayer
    sip.delete(layerDeletes)
    del layerDeletes
    return result


def getChangeSetRaw(fname):
    layerDeletes = QgsVectorLayer(fname + "|layername=geogig_deleted_rows")
    layerDeletes_fts = list(layerDeletes.getFeatures())
    layerDeletes_fids = [f["fid"] for f in layerDeletes_fts]


    sip.delete(layerDeletes)
    del layerDeletes

    layerUpdates = QgsVectorLayer(fname + "|layername=geogig_updated_rows_orig")
    layerUpdates_fts = list(layerUpdates.getFeatures())
    layerUpdates_fids = [f["fid"] for f in layerUpdates_fts]

    sip.delete(layerUpdates)
    del layerUpdates

    layerAdds = QgsVectorLayer(fname + "|layername=geogig_inserted_rows")
    layerAdds_fts = list(layerAdds.getFeatures())
    layerAdds_fids = [f["fid"] for f in layerAdds_fts]

    sip.delete(layerAdds)
    del layerAdds

    deleted_fts = [f for f in layerDeletes_fts if f["fid"] not in layerAdds_fids]
    inserted_fids = difference(layerAdds_fids,layerDeletes_fids)
    updated_fids = difference(difference(layerUpdates_fids,inserted_fids), layerDeletes_fids)

    return {"deleted_fids": [f["fid"] for f in deleted_fts],
            "deleted_geogigids": [f[GEOGIGID_FIELD] for f in deleted_fts],
            "inserted_fids": inserted_fids,
            "updated_fids": updated_fids}



def clearAuditTables(fname):
    layerAdds = QgsVectorLayer(fname + "|layername=geogig_inserted_rows")
    r = layerAdds.dataProvider().truncate()
    sip.delete(layerAdds)
    del layerAdds

    layerDeletes = QgsVectorLayer(fname+"|layername=geogig_deleted_rows")
    r =layerDeletes.dataProvider().truncate()
    sip.delete(layerDeletes)
    del layerDeletes

    layerUpdates = QgsVectorLayer(fname+"|layername=geogig_updated_rows_orig")
    r =layerUpdates.dataProvider().truncate()
    sip.delete(layerUpdates)
    del layerUpdates




# DIFF is a  list of
# {
#  'ID':<geogig ID - string>,
#  'geogig.changeType':  - int 0=add,1=modify,2=delete,
#  'old': <QgsFeature> -- old feature (None if add)
#  'new': <QgsFeature> -- new feature (None if delete)
# }
def applyDiff(fname, layername, diff):
    layer = QgsVectorLayer(fname + "|layername=" + layername)

    adds = [f["new"] for f in diff if f['geogig.changeType']==0]
    addFeaturesToLayer(layer,adds)

    mods = [f for f in diff if f['geogig.changeType'] == 1]
    mods_org = getFeaturesFromGeogigIds([f["ID"] for f in mods], layer)
    mods_new = {f["ID"]:f["new"] for f in mods}
    replaceFeaturesInLayer(layer, mods_org, mods_new)

    dels = [f for f in diff if f['geogig.changeType'] == 2]
    dels_org = getFeaturesFromGeogigIds([f["ID"] for f in dels], layer).values()
    r = layer.dataProvider().deleteFeatures([f.id() for f in dels_org])

    sip.delete(layer)
    del layer


# the base fname for a geopkg should not have the "|layername=..." in it.
# this will remove it if its there...
def simplifyGeoPKGFname(fname):
    idx = fname.find("|")
    if idx == -1:
        return fname
    return fname[:idx]

