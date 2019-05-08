Styles for GeoGig Layers
================================

Apart from layer data, a GeoGig repository can contain style data. Style data is used when a layer is added from a GeoGig repository, whether as a live layer or a GeoPackage one. This is a simple tool to make managing styles easier.

Adding a Style when Importing a Layer
--------------------------------------

When a layer is added to a geogig repository, its style in the current QGIS project is automatically uploaded to the repository. When you later add that layer from the repository into another project, the style will be used by QGIS.

Modifying the Default Style for a GeoGig Layer
-----------------------------------------------

You can modify the style of a GeoGig layer in your QGIS project, but that change won't be added to the repository automatically. New layers added from the repository will use the original default style that is saved in the repository. If you want to set a new default style, right-click on the layer item in the QGIS :guilabel:`Layers` panel and select :guilabel:`GeoGig --> Save Layer Style as Default Style`. The current style of the layer will be set in the repository as the new default style.  


When you add the layer from that repository, it will be added pre-styled with the style you saved.  Each repository can have a different style.  When you fork a repository, the new repository will also contain any styles that were present at the time you forked.  A Pull Request only moves dataset changes (not styles).  To move a style from one repository to another repository:

1. Add the layer from the repository with the style you want.
2. Copy the style of that layer, right-clicking on it and selecting :guilabel:`Styles --> Copy Style --> Symbology`.

NOTE: do not use the :guilabel:`All Style Categories` option. That would copy additional GeoGig information from the origin layer, and could cause problems in the the destination layer.

3. Add the layer from the repository you want to update.
4. Paste the style into this new layer, right-click on the layer and select :guilabel:`Styles --> Paste Style --> Symbology`.
5. Right-click on this layer and select :guilabel:`GeoGig --> Save Layer Style as Default Style`.

 


