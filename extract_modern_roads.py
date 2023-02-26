'''
@author: Stephen Gadd, Docuracy Ltd, UK

The function extract_modern_roads extracts the LineStrings from a shapefile 
which lie within the extent of a given geotiff.

'''

import os
from shapely.geometry import box
import geopandas as gpd
from shapely.geometry import LineString
import rasterio.transform

def transform_linestrings(directory, transformation):
    # Read the linestrings from the GeoPackage
    gdf = gpd.read_file(directory + 'desCartes.gpkg', layer='modern_roads')
    
    # Get the coordinates of the linestrings as a list of tuples, then transform to pixel coordinates
    coords_list = list(gdf.geometry.apply(lambda geom: list(geom.coords)).values)
    transformed_gdf = gpd.GeoDataFrame(geometry=gpd.GeoSeries([LineString([(coord[1], coord[0]) for coord in [rasterio.transform.rowcol(transformation, coord[0], coord[1]) for coord in coords]]) for coords in coords_list]))
    transformed_gdf['id'] = gdf['id'].values
    
    return gdf, transformed_gdf # as a GeoDataFrame 

def extract_modern_roads(DATADIR, OUTPUTDIR, ROADFILE, LOCATION_NAME, EXTENT, shapefile=False):
    
    gdf = gpd.read_file(
        DATADIR + ROADFILE,
        layer=os.path.splitext(ROADFILE)[0],
        bbox=tuple(EXTENT)
    )
    # Specifying EXTENT above does not cause linestrings partly within the extent to be cropped to the extent
    cropped_gdf = gpd.clip(gdf, box(*EXTENT))
    cropped_gdf = cropped_gdf[~cropped_gdf.is_empty]
    cropped_gdf = cropped_gdf.explode(index_parts=True)  # Cropping can cause creation of multiparts 
    cropped_gdf.to_file(OUTPUTDIR + 'desCartes.gpkg', layer="modern_roads", driver="GPKG")
    if shapefile:
        root, _ = os.path.splitext(ROADFILE)
        cropped_gdf.to_file(OUTPUTDIR + root + '.shp')
