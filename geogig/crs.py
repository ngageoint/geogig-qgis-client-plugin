from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsRectangle, QgsProject


crslatlong = QgsCoordinateReferenceSystem.fromProj4("+proj=latlong")

def xform(extent, srcCRS, destCRS):
    if srcCRS == destCRS:
        return extent  # nothing to do

    # cut down the extent so it's not too big

    # clamped to the projection's valid area (usually small)
    projectionClampedExtent = clampToProjectionExtent(extent, srcCRS)

    # clamped to the world (might not work in some projections)
    worldClampedExtent = clampToWorld(extent, srcCRS)

    # xform the two extents to the dest CRS

    transform = QgsCoordinateTransform(srcCRS, destCRS, QgsProject.instance())

    xformed_projectionClamped = QgsRectangle()  # null rect
    if not projectionClampedExtent.isNull():
        xformed_projectionClamped = transform.transformBoundingBox(projectionClampedExtent)

    xformed_worldClamped = QgsRectangle()  # null rect
    if not worldClampedExtent.isNull():
        xformed_worldClamped = transform.transformBoundingBox(worldClampedExtent)


    # make final choice of what to use
    # we WANT to use the world one, but sometimes cannot

    # indicates everything is ok -- likely no projection blowing up
    if xformed_worldClamped.contains(xformed_projectionClamped):
        return xformed_worldClamped  # likely good

    # if one is null, return the other
    if xformed_projectionClamped.isNull():
        return xformed_worldClamped

    if xformed_worldClamped.isNull():
        return xformed_projectionClamped

    # clamp to the destination CRS (last resort to try to get something valid)
    return clampToProjectionExtent(xformed_worldClamped, destCRS)

# extent - an extent (in proj CRS)
# returns an extent that is the same or smaller, but constrained
# to the projection's max bounds.
#
# if we don't know the projection's bounds, we use the world.
#
# NOTE: it might be better to use the whole world in all cases, but it has the possibility of
#       having bad values.  Using the projection bounds might clip when it likely doesn't
#       need to (although, you shouldn't be viewing data outside the projection's bounds).
def clampToProjectionExtent(extent, proj):
    validextent = proj.bounds()
    if validextent.isNull():
        validextent = QgsRectangle(-179.9999999, -89.9999999, 179.9999999, 89.9999999)  # best guess
    transform = QgsCoordinateTransform(crslatlong, proj, QgsProject.instance())
    projectedCRSExtent = transform.transformBoundingBox(validextent)
    # insideSrc = projectedCRSExtent.contains(extent)
    extent_clamped = projectedCRSExtent.intersect(extent)
    return extent_clamped

def clampToWorld(extent, proj):
    # world
    validextent = QgsRectangle(-179.9999999, -89.9999999, 179.9999999, 89.9999999)  # best guess
    transform = QgsCoordinateTransform(crslatlong, proj, QgsProject.instance())
    projectedCRSExtent = transform.transformBoundingBox(validextent)
    extent_clamped = projectedCRSExtent.intersect(extent)
    return extent_clamped
