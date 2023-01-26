# desCartes

***desCartes* recognises roads on old maps, and converts them to vector lines that can be used in GIS applications and historical transport network analysis.**

For any given map [extent](https://en.wikipedia.org/wiki/Map_extent) (bounding coordinates), desCartes first generates a a georeferenced map image ([geotiff](https://en.wikipedia.org/wiki/GeoTIFF)), and then processes the image to extract candidate road lines. These lines are then tested for similarity against an idealised road template, and matched by proximity and orientation to modern road vectors. Gaps in the road lines are then filled (and junctions made) where appropriate, and each line is assigned a certainty score and (where possible) the id of the matching modern road segment.

desCartes is pre-configured for use with the [National Library of Scotland](https://maps.nls.uk/os/)'s 19th-century 6":1 mile GB Ordnance Survey map tiles served by [MapTiler Cloud](https://cloud.maptiler.com/tiles/uk-osgb10k1888/), but might be adapted to suit other maps.
