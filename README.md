# *des*Cartes

***des*Cartes recognises roads on old maps, and converts them to vector lines that can be used in GIS applications and historical transport network analysis.** *It is currently under development.*

><img src="https://user-images.githubusercontent.com/42514781/215267775-a8f1ed7e-5fd2-48e8-893d-7fb82f3ac3df.png" />
>
>Output from *des*Cartes visualised using QGIS. Red lines are roads which have been matched to modern road vectors (green); yellow lines indicate where roads might have been detected, their opacity an indication of certainty. 

For any given map [extent](https://en.wikipedia.org/wiki/Map_extent) (bounding coordinates), *des*Cartes first generates a georeferenced map image ([geotiff](https://en.wikipedia.org/wiki/GeoTIFF)), and then processes the image to extract candidate road lines. These lines are then tested for similarity against an idealised road template, and matched by proximity and orientation to modern road vectors. Gaps in the road lines are then filled (and junctions made) where appropriate, and each line is assigned a certainty score and (where possible) the id of the matching modern road segment.

*des*Cartes is pre-configured for use with the [National Library of Scotland](https://maps.nls.uk/os/)'s 19th-century 6":1 mile GB Ordnance Survey map tiles served by [MapTiler Cloud](https://cloud.maptiler.com/tiles/uk-osgb10k1888/), and with the modern [Ordnance Survey Open Roads](https://beta.ordnancesurvey.co.uk/products/os-open-roads) vector dataset, but might be adapted to suit other maps.

## Live Demo

[Click here](https://descartes.viaeregiae.org/git/webapp/desCartes_demo.html) for a very limited live demonstration of *des*Cartes in your browser, where you can select a small area on a map and see the results of image processing. Map tileset selection, vector processing, and download of the extracted road vectors as a shapefile are not yet part of this demonstration. 

Please follow [@docuracy](https://twitter.com/docuracy) on Twitter or [@stephengadd@mstdn.social](https://mstdn.social/@stephengadd) on Mastodon for updates.
