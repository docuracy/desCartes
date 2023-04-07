'''
@author: Stephen Gadd, Docuracy Ltd, UK
Adapted from https://github.com/jimutt/tiles-to-tiff

This script is used to create a geotiff file from a tile source. It uses the 
GDAL library to fetch, georeference and merge tiles of an image. The script 
takes in the tile source, output directory, geotiff name, bounding box and 
zoom level as input. The bounding box is used to calculate the range of x and 
y coordinates of the tiles that need to be fetched. Once all the tiles are 
fetched, they are georeferenced and merged to create a single geotiff file.

'''

import urllib.request
import os
import glob
import shutil
from tile_convert import bbox_to_xyz, tile_edges
from osgeo import gdal
import pyproj as proj
import hashlib
import base64

temp_dir = os.path.join(os.path.dirname(__file__), 'temp')

def fetch_tile(x, y, z, tile_source, cache_dir):
    
    cache_path = f'{cache_dir}/{x}_{y}_{z}.jpg'
    if os.path.exists(cache_path):
        shutil.copy(cache_path, temp_dir)
        return cache_path
    
    url = tile_source.replace(
        "{x}", str(x)).replace(
        "{y}", str(y)).replace(
        "{z}", str(z))

    if not tile_source.startswith("http"):
        return url.replace("file:///", "")

    path = f'{temp_dir}/{x}_{y}_{z}.jpg'
    req = urllib.request.Request(
        url,
        data=None,
        headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) tiles-to-tiff/1.0 (+https://github.com/jimutt/tiles-to-tiff)'
        }
    )
    g = urllib.request.urlopen(req)
    with open(path, 'b+w') as f:
        f.write(g.read())
    return path


def merge_tiles(input_pattern, output_path, extent):
    vrt_path = os.path.join(temp_dir, "tiles.vrt")
    gdal.BuildVRT(vrt_path, glob.glob(input_pattern))
    gdal.Translate(output_path, vrt_path, outputSRS='EPSG:4326', projWin=[extent[0], extent[3], extent[2], extent[1]])


def georeference_raster_tile(x, y, z, path):
    bounds = tile_edges(x, y, z)
    
    #crs_wgs = proj.Proj(init='epsg:4326') # WGS84 geographic
    #crs_bng = proj.Proj(init='epsg:27700') # British National Grid
    #bounds[0],bounds[1] = proj.transform(crs_wgs, crs_bng, bounds[0], bounds[1])
    #bounds[2],bounds[3] = proj.transform(crs_wgs, crs_bng, bounds[2], bounds[3])
    
    gdal.Translate(os.path.join(temp_dir, f'{temp_dir}/{x}_{y}_{z}.tif'),
                   path,
                   # outputSRS='EPSG:3857',
                   outputSRS='EPSG:4326', # Longitude, Latitude
                   #outputSRS='EPSG:27700',
                   outputBounds=bounds)

def create_geotiff(tile_source, output_dir, geotiff_name, bounding_box, zoom): 
    print(f"Bounding box length: {len(bounding_box)}")
    print(f"Bounding box content: {bounding_box}")
    
    if len(bounding_box) == 2:
        lon_min, lat_min = bounding_box[0]
        lon_max, lat_max = bounding_box[1]
    else:
        lon_min, lat_min, lon_max, lat_max = bounding_box
    
    # Create a cache directory name
    hash_obj = hashlib.sha256(tile_source.encode())
    hash_bytes = hash_obj.digest()
    hash_b64 = base64.urlsafe_b64encode(hash_bytes).decode()
    cache_dir = os.path.join(os.path.dirname(__file__), "data", "cache", hash_b64)

    # Script start:
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    x_min, x_max, y_min, y_max = bbox_to_xyz(
        lon_min, lon_max, lat_min, lat_max, zoom)

    print(f"Fetching & georeferencing {(x_max - x_min + 1) * (y_max - y_min + 1)} tiles")

    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            try:
                png_path = fetch_tile(x, y, zoom, tile_source, cache_dir)
                print(f"{x},{y} {'found in cache.' if cache_dir in png_path else 'fetched from tileserver.'}")
                georeference_raster_tile(x, y, zoom, png_path)
            except OSError:
                print(f"Error, failed to get {x},{y}")
                pass

    print("Resolving and georeferencing of raster tiles complete")

    print("Merging tiles ...")
    filename = os.path.join(output_dir, geotiff_name)
    merge_tiles(os.path.join(temp_dir, '*.tif'), filename, bounding_box)
    print("... complete")
    
    # input_raster = gdal.Open(WGS84_filename)
    # output_raster = output_dir + '/' + geotiff_name
    # kwargs = {'dstAlpha': True}
    # warp = gdal.Warp(output_raster,input_raster,dstSRS='EPSG:27700',**kwargs)
    # warp = None # Closes the files
    
    # Move any downloaded files to the cache folder
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    for file in os.listdir(temp_dir):
        if file.endswith(".jpg"):
            shutil.move(os.path.join(temp_dir, file), os.path.join(cache_dir, file))

    shutil.rmtree(temp_dir)
    
    return filename
    