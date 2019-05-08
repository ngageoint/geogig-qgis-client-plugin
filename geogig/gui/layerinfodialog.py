from qgis.core import QgsMessageOutput

def asHTML(infoJson):
    name = infoJson["name"]
    title = infoJson["title"] if infoJson["title"] is not None else ""
    abstract = infoJson["abstract"] if infoJson["abstract"] is not None else ""


    html = "<p><b>Basic info:</b></p><table border=1 cellpadding='6'>"
    html += "<tr><td>Name</td><td>"+name+"</td></tr>"
    html += "<tr><td>Title</td><td>"+title+"</td></tr>"
    html += "<tr><td>Abstract</td><td>" + abstract + "</td></tr>"
    html += "<tr><td>N Features</td><td>" + "{:,}".format(infoJson["size"])   + "</td></tr>"
    html += "<tr><td>Bounds</td><td>" + str(infoJson["bounds"]) + "</td></tr>"
    html += "</table>"

    html += "<br><p><b>Layer schema:</b></p>"

    html += "<table border=1 cellpadding='6'>"
    for prop in infoJson["type"]["properties"]:
            crs = ""
            if prop["crs"] is not None and prop["crs"]["authorityCode"] is not None:
                crs = prop["crs"]["authorityCode"]
            html += "<tr><td>"+prop["name"]+"</td><td>"+prop["binding"]+"</td><td>"+crs+"</td></tr>"
    html += "</table>"
    return html

def showLayerInfo(server,userName,repoName,layerName):
    infoJson = server.layerInfo(userName, repoName, layerName)
    txt = asHTML(infoJson)
    dlg = QgsMessageOutput.createMessageOutput()
    dlg.setTitle("Layer " + layerName)
    dlg.setMessage(txt, QgsMessageOutput.MessageHtml)
    dlg.showMessage()
