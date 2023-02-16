# *des*Cartes

***des*Cartes recognises roads on old maps, and converts them to vector lines that can be used in GIS applications and historical transport network analysis.** *It is currently under development.*

><img src="https://user-images.githubusercontent.com/42514781/219341848-9d578564-f8a1-48d7-b13b-5a64c610ae3a.jpeg" />
>
>Output from *des*Cartes. Areas are shaded by colour to indicate the criteria by which they were rejected as candidate roads. Likely roads are indicated by yellow lines, less-likely roads by blue lines. *Further development will focus on improved discrimination between likely and less-likely roads, and on patching small gaps to establish a road network.*

For any given map [extent](https://en.wikipedia.org/wiki/Map_extent) (bounding coordinates), *des*Cartes first generates a georeferenced map image ([geotiff](https://en.wikipedia.org/wiki/GeoTIFF)), and then - using a range of adjustable input parameters - processes the image to extract candidate road lines.

><img src="https://user-images.githubusercontent.com/42514781/219344526-67aeb374-7e20-4cc7-82bd-8a7383283675.png" />
>
>Demonstration of *des*Cartes. The user can select a map area (for the sake of server resources currently limited to a maximum of 10 square kilometers) and adjust the parameters used to detect likely roads.


><img src="https://user-images.githubusercontent.com/42514781/219343478-be3ce80c-21ed-4719-924f-4722e76419c0.png" />
>
>Output from *des*Cartes. A range of images is presented to indicate the steps taken in identifying likely roads, and a button is provided for the download of vector data.

*des*Cartes is pre-configured for use with the [National Library of Scotland](https://maps.nls.uk/os/)'s 19th-century 6":1 mile GB Ordnance Survey map tiles served by [MapTiler Cloud](https://cloud.maptiler.com/tiles/uk-osgb10k1888/), but might be adapted to suit other maps.

## Live Demo

[Click here](https://bit.ly/desCartes-demo) for a limited live demonstration of *des*Cartes in your browser, where you can select a small area on a map and see the results of image processing. Map tileset selection is not yet part of this demonstration. 

Please follow [@docuracy](https://twitter.com/docuracy) on Twitter or [@stephengadd@mstdn.social](https://mstdn.social/@stephengadd) on Mastodon for updates.
