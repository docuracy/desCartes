'''
@author: Stephen Gadd, Docuracy Ltd, UK

The function extract_modern_roads extracts the LineStrings from a shapefile 
which lie within the extent of a given geotiff.

'''

import subprocess, os
from shapely.geometry import Polygon, box
# from osgeo import gdal
# from osgeo import ogr
# from osgeo import osr
import pandas as pd
import geopandas as gp

def extract_modern_roads(DATADIR, mapfile, OUTPUTDIR, ROADFILE, LOCATION_NAME, EXTENT):
    
    # Use ogr2ogr to extract the LineStrings from the .gpkg file
    ogrcmd = """ogr2ogr -f "ESRI Shapefile" -nlt LINESTRING -explodecollections -spat %s %s %s %s "%s" "%s" """%(EXTENT[0], EXTENT[1], EXTENT[2], EXTENT[3], OUTPUTDIR, DATADIR+ROADFILE)
    response = subprocess.check_output(ogrcmd, shell=True)
    
    # Now crop the LineStrings to the map extent
    root, ext = os.path.splitext(ROADFILE)
    shapefile = OUTPUTDIR + root + '.shp'
    gdf = gp.read_file(shapefile)
    bbox = box(*EXTENT)
    cropped_gdf = gp.clip(gdf, bbox)
    cropped_gdf = cropped_gdf[~cropped_gdf.is_empty]
    cropped_gdf.to_file(shapefile)
