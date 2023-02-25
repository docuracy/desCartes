# *des*Cartes

***des*Cartes recognises roads on old maps, and converts them to vector lines that can be used in GIS applications and historical transport network analysis.** *It is currently under development.*

><img src="https://user-images.githubusercontent.com/42514781/219341848-9d578564-f8a1-48d7-b13b-5a64c610ae3a.jpeg" />
>
>Output from *des*Cartes. Areas are shaded by colour to indicate the criteria by which they were rejected as candidate roads. Candidate road vectors are scored based on their adherence to map contours and their similarity to modern roads, and their score is reflected in the opacity of the yellow lines. Blue lines are un-scored gap-fillers.

For any given map [extent](https://en.wikipedia.org/wiki/Map_extent) (bounding coordinates), *des*Cartes first generates a georeferenced map image ([geotiff](https://en.wikipedia.org/wiki/GeoTIFF)), and then - using a range of adjustable input parameters - processes the image to extract candidate road lines.

><img src="https://user-images.githubusercontent.com/42514781/221323460-0a761a91-5e10-4ffd-8441-06a80084fc37.png" />
>
>Demonstration of *des*Cartes. The user can select a map area (for the sake of server resources currently limited to a maximum of 10 square kilometers) and adjust the parameters used to detect likely roads.

><img src="https://user-images.githubusercontent.com/42514781/219343478-be3ce80c-21ed-4719-924f-4722e76419c0.png" />
>
>Output from *des*Cartes. A range of images is presented to indicate the steps taken in identifying likely roads, and a button is provided for the download of vector data.

><img src="https://user-images.githubusercontent.com/42514781/221306707-ff0730ed-f357-4330-addf-61fc5394e40b.png" />
>
>This image shows the tests run along the contours of a skeletonized image to determine the presence or otherwise of road boundaries or modern roads (shown in yellow). Shape filtering before running these tests would eliminate most of the false contours in white areas. The modern road tests check not only the presence of a road in the vicinity, but also its orientation relative to the candidate road. 

><img src="https://user-images.githubusercontent.com/42514781/221305212-d6d0b5dc-1f1b-4845-8b17-cff64f1a59ac.png" />
>
>The latest development is the inclusion of network analysis which aims to group candidate roads into a likely network, patching gaps where necessary. Candidate roads which fail a connectivity test are eliminated. Parameters for tuning the analysis are yet to be properly determined, and in the meantime results range from terrible to impressively good!

*des*Cartes is pre-configured for use with the [National Library of Scotland](https://maps.nls.uk/os/)'s 19th-century 6":1 mile GB Ordnance Survey map tiles served by [MapTiler Cloud](https://cloud.maptiler.com/tiles/uk-osgb10k1888/), but might be adapted to suit other maps.

## Live Demo

[Click here](https://bit.ly/desCartes-demo) for a limited live demonstration of *des*Cartes in your browser, where you can select a small area on a map and see the results of image processing, and download a GeoPackage of the predicted road network for use in GIS software. Choose from several preconfigured map tilesets, or experiment with your own.

Development and server costs are entirely self-funded. Please [donate](https://ko-fi.com/docuracy) if you can. Commissions for customised development are welcome!

Follow [@docuracy](https://twitter.com/docuracy) on Twitter or [@stephengadd@mstdn.social](https://mstdn.social/@stephengadd) on Mastodon for updates.
