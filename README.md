# *des*Cartes

***des*Cartes recognises roads on old maps, and converts them to vector lines that can be used in GIS applications and historical transport network analysis.** *It is currently under development, but you can try a [limited live demo](https://github.com/docuracy/desCartes/edit/main/README.md#live-demo).*

## Black & White Maps

For any given map [extent](https://en.wikipedia.org/wiki/Map_extent) (bounding coordinates), *des*Cartes first generates a georeferenced map image ([geotiff](https://en.wikipedia.org/wiki/GeoTIFF)), and then - using a range of adjustable input parameters - processes the image to extract candidate road lines.

><img src="https://user-images.githubusercontent.com/42514781/221323460-0a761a91-5e10-4ffd-8441-06a80084fc37.png" />
>
>Demonstration of *des*Cartes. The user can select a map area (for the sake of server resources currently limited to a maximum of 10 km² for maps at this scale) and adjust the parameters used to detect likely roads.

><img src="https://user-images.githubusercontent.com/42514781/219343478-be3ce80c-21ed-4719-924f-4722e76419c0.png" />
>
>Output from *des*Cartes. A range of images is presented to indicate the steps taken in identifying likely roads, and a button is provided for the download of vector data.

><img src="https://user-images.githubusercontent.com/42514781/221306707-ff0730ed-f357-4330-addf-61fc5394e40b.png" />
>
>This image shows the tests run along the contours of a skeletonized image to determine the presence or otherwise of road boundaries or modern roads (shown in yellow). Shape filtering before running these tests would eliminate most of the false contours in white areas. The modern road tests check not only the presence of a road in the vicinity, but also its orientation relative to the candidate road. 

><img src="https://user-images.githubusercontent.com/42514781/221305212-d6d0b5dc-1f1b-4845-8b17-cff64f1a59ac.png" />
>
>Network analysis aims to group candidate roads into a likely network, patching gaps where necessary. Candidate roads which fail a connectivity test are eliminated. Parameters for tuning the analysis are yet to be properly determined, and in the meantime results range from terrible to impressively good!

><img src="https://user-images.githubusercontent.com/42514781/219341848-9d578564-f8a1-48d7-b13b-5a64c610ae3a.jpeg" />
>
>Output from *des*Cartes. Areas are shaded by colour to indicate the criteria by which they were rejected as candidate roads. Candidate road vectors are scored based on their adherence to map contours and their similarity to modern roads, and their score is reflected in the opacity of the yellow lines. Blue lines are un-scored gap-fillers.

## Coloured Maps

Extracting road vectors from coloured maps poses a different set of challenges.

><img src="https://user-images.githubusercontent.com/42514781/223348760-6e849bd8-b16e-4abe-85d6-c1e1b6f56497.png" />
>
>In this map, the roads of interest are coloured red, brown, and yellow. Complications arise because parts of the roads are obliterated by text and map features, and these colours are also used for things like elevation contours, road numbering, and railway stations.

><img src="https://user-images.githubusercontent.com/42514781/223349099-ba375a14-b1ce-4886-b931-88c87c40fc3a.png" />
>
>In the demo, an area up to 40 km² can be selected by the user. Results include images showing the colours extracted from the map, an edited, "skeletonized", and vectorised version of the colour map, and another version in which the gaps have been patched.

><img src="https://user-images.githubusercontent.com/42514781/223348833-542d0a07-ea23-4440-b4bc-7e1380cb9203.png" />
>
>Extracted colours, with configured shapes removed (in this case, the railway station). Road numbering remains, and there are some quite large gaps where roads were obliterated by other features.

><img src="https://user-images.githubusercontent.com/42514781/223348867-62c345ad-9623-4c8b-a060-3de3be2d4ea0.png" />
>
>The coloured shapes are then thinned down to a single-pixel width, and then traced (by processing contours) too produce gappy vector lines.

><img src="https://user-images.githubusercontent.com/42514781/223348896-24de5e47-81d8-4094-8ec9-4b471c446beb.png" />
>
>Gaps are closed by a variety of techniques, which include extending each line a pixel at a time to see if it meets another extending line within a given distance, linking unconncected endpoints to nearest lines, and snapping near-coincident endpoints.

## Development Roadmap

- [ ] Improve 1890s B&W vectorisation by reference to vectorised 1950s coloured map framework ([Issue #11](https://github.com/docuracy/desCartes/issues/11)).
- [ ] Refine processing parameters through machine learning ([Issue #4](https://github.com/docuracy/desCartes/issues/4)).

## Live Demo

[Click here](https://bit.ly/desCartes-demo) for a limited live demonstration of *des*Cartes in your browser, where you can select a small area on a map and see the results of image processing, and download a GeoPackage of the predicted road network for use in GIS software. Choose from several preconfigured map tilesets, or experiment with your own.

### Map Tile Sources

*des*Cartes might be adapted to suit other maps, but is pre-configured for use with:
+ The [National Library of Scotland](https://maps.nls.uk/os/)'s GB Ordnance Survey map tiles served by [MapTiler Cloud](https://cloud.maptiler.com/tiles/).
  + [Six-Inch to the mile, 1888-1913](https://cloud.maptiler.com/tiles/uk-osgb10k1888/)
  + [One-Inch Seventh Series, 1955-1961](https://cloud.maptiler.com/tiles/uk-osgb63k1955/)
+ A small selection of the [British Library](https://www.bl.uk/collection-guides/ordnance-survey-mapping)'s early 19th-century [GB Ordnance Survey drawings](https://commons.wikimedia.org/wiki/Category:Ordnance_Survey_Drawings).
+ The vectorised modern UK road network from [Ordnance Survey Open Roads](https://www.ordnancesurvey.co.uk/business-government/products/open-map-roads).

---

**Development and server costs are entirely self-funded. Please [donate](https://ko-fi.com/docuracy) if you can. Commissions for customised development are welcome!**

Follow [@docuracy](https://twitter.com/docuracy) on Twitter or [@stephengadd@mstdn.social](https://mstdn.social/@stephengadd) on Mastodon for updates.
