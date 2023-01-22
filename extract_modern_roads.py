
import subprocess
from shapely.geometry import Polygon
from osgeo import gdal
from osgeo import ogr
from osgeo import osr
import pandas as pd
import geopandas as gp

def extract_modern_roads(DATADIR, mapfile, OUTPUTDIR, ROADFILE, LOCATION_NAME):

    ogr2ogr = r'C:\OSGeo4W\bin\ogr2ogr.exe'
    
    raster = gdal.Open(mapfile)
    gt = raster.GetGeoTransform()
    pixelSizeX = gt[1]
    pixelSizeY =-gt[5]
    
    ogrcmd = """ogr2ogr -f "ESRI Shapefile" -nlt LINESTRING -explodecollections -spat %s %s %s %s "%s" "%s" """%(gt[0], gt[3] - pixelSizeY * raster.RasterYSize, gt[0] + pixelSizeX * raster.RasterXSize, gt[3],OUTPUTDIR,DATADIR+ROADFILE)
    response = subprocess.check_output(ogrcmd, shell=True)
        
    del raster