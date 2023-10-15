'''
map_from_tiles.py

@author: Stephen Gadd, Docuracy Ltd, UK
Adapted from https://github.com/jimutt/tiles-to-tiff

This script is used to create a georeferenced map from a tile source. It uses
the GDAL library to fetch, georeference and merge tiles of an image. The script
takes in the tile source, output directory, map name, bounding box and
zoom level as input. The bounding box is used to calculate the range of x and
y coordinates of the tiles that need to be fetched. Once all the tiles are
fetched, they are georeferenced and merged to create a single map file.

'''

import urllib.request
import os
import glob
import shutil
from osgeo import gdal
import pyproj as proj
import hashlib
import base64
from math import log, tan, radians, cos, pi, floor, degrees, atan, sinh

def sec(x):
    return(1/cos(x))


def latlon_to_xyz(lat, lon, z):
    tile_count = pow(2, z)
    x = (lon + 180) / 360
    y = (1 - log(tan(radians(lat)) + sec(radians(lat))) / pi) / 2
    return(tile_count*x, tile_count*y)


def bbox_to_xyz(lon_min, lon_max, lat_min, lat_max, z):
    x_min, y_max = latlon_to_xyz(lat_min, lon_min, z)
    x_max, y_min = latlon_to_xyz(lat_max, lon_max, z)
    return(floor(x_min), floor(x_max),
           floor(y_min), floor(y_max))


def mercatorToLat(mercatorY):
    return(degrees(atan(sinh(mercatorY))))


def y_to_lat_edges(y, z):
    tile_count = pow(2, z)
    unit = 1 / tile_count
    relative_y1 = y * unit
    relative_y2 = relative_y1 + unit
    lat1 = mercatorToLat(pi * (1 - 2 * relative_y1))
    lat2 = mercatorToLat(pi * (1 - 2 * relative_y2))
    return(lat1, lat2)


def x_to_lon_edges(x, z):
    tile_count = pow(2, z)
    unit = 360 / tile_count
    lon1 = -180 + x * unit
    lon2 = lon1 + unit
    return(lon1, lon2)


def tile_edges(x, y, z):
    lat1, lat2 = y_to_lat_edges(y, z)
    lon1, lon2 = x_to_lon_edges(x, z)
    return[lon1, lat1, lon2, lat2]


def fetch_tile(x, y, z, tile_source, cache_dir):

    cache_path = f'{cache_dir}/{x}_{y}_{z}.jpg'
    if os.path.exists(cache_path):
        shutil.copy(cache_path, temp_dir)
        return cache_path

    url = tile_source.replace(
        "{x}", str(x)).replace(
        "{y}", str(y)).replace(
        "{z}", str(z)).replace(
        "%7Bx%7D", str(x)).replace(
        "%7By%7D", str(y)).replace(
        "%7Bz%7D", str(z))

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

def merge_tiles(input_pattern, output_path, extent, crs):
    vrt_path = os.path.join(temp_dir, "tiles.vrt")
    gdal.BuildVRT(vrt_path, glob.glob(input_pattern))
    print(f'Projecting {extent} to {crs}')
    gdal.Translate(output_path, vrt_path, outputSRS=crs, projWin=[extent[0], extent[3], extent[2], extent[1]], format='JPEG', creationOptions=['PIXELTYPE=U32', 'JPEG_QUALITY=100', 'JPEG_SUBSAMPLE=0'])
    #gdal.Translate(output_path, vrt_path, outputSRS=crs, projWin=[extent[0], extent[3], extent[2], extent[1]], format='JPEG', creationOptions=['PIXELTYPE=U32', 'QUALITY=100', 'PROGRESSIVE=YES'])
    #gdal.Translate(output_path, vrt_path, outputSRS=crs, projWin=[extent[0], extent[3], extent[2], extent[1]], format='PNG', creationOptions=['COMPRESS=DEFLATE', 'ZLEVEL=9'])
    #gdal.Translate(output_path, vrt_path, outputSRS=crs, projWin=[extent[0], extent[3], extent[2], extent[1]], format='GTiff')

def georeference_raster_tile(x, y, z, path, crs):
    bounds = tile_edges(x, y, z)

    # Create the projection transformer and transform from EPSG:4326
    transformer = proj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    bounds[0],bounds[1] = transformer.transform(bounds[0], bounds[1])
    bounds[2],bounds[3] = transformer.transform(bounds[2], bounds[3])

    gdal.Translate(os.path.join(temp_dir, f'{temp_dir}/{x}_{y}_{z}.jpeg'),
                   path,
                   outputSRS=crs,
                   outputBounds=bounds,
                   width=256,
                   height=256, format='JPEG', creationOptions=['PIXELTYPE=U32', 'QUALITY=100', 'PROGRESSIVE=YES'])

def create_map(tile_source, output_dir, map_name, bounding_box, zoom, crs, temp_dir, cache_dir_root):

    bounding_box_original = bounding_box

    if not crs == 'EPSG:4326':

        # Create the projection transformer to EPSG:4326
        transformer = proj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

        # Extract the coordinates of the extent
        xminOld, yminOld, xmaxOld, ymaxOld = bounding_box

        # Use the transformer to convert the extent
        xmin4326, ymin4326 = transformer.transform(xminOld, yminOld)
        xmax4326, ymax4326 = transformer.transform(xmaxOld, ymaxOld)

        bounding_box = (xmin4326, ymin4326, xmax4326, ymax4326)

    # Print the extent
    print(f"Extent of {map_name}: {bounding_box}")

    lon_min, lat_min, lon_max, lat_max = bounding_box

    # Create a cache directory name
    hash_obj = hashlib.sha256(tile_source.encode())
    hash_bytes = hash_obj.digest()
    hash_b64 = base64.urlsafe_b64encode(hash_bytes).decode()
    cache_dir = os.path.join(cache_dir_root, hash_b64)

    # Script start:
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    x_min, x_max, y_min, y_max = bbox_to_xyz(
        lon_min, lon_max, lat_min, lat_max, zoom)

    total_tiles = (x_max - x_min + 1) * (y_max - y_min + 1)
    counter = 0
    print(f"Fetching & georeferencing {total_tiles} tiles")

    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            counter += 1
            try:
                png_path = fetch_tile(x, y, zoom, tile_source, cache_dir)
                percent_done = counter / total_tiles * 100
                print(f"{percent_done:.1f}% : {x},{y} {'found in cache.' if cache_dir in png_path else 'fetched from tileserver.'}", end='\r')
                georeference_raster_tile(x, y, zoom, png_path, crs)
            except OSError:
                print(f"Error, failed to get {x},{y}")
                pass

    print("Resolving and georeferencing of raster tiles complete")

    print("Merging tiles ...")
    filename = os.path.join(output_dir, map_name)
    merge_tiles(os.path.join(temp_dir, '*.jpeg'), filename, bounding_box_original, crs)
    print("... complete")

    # Move any downloaded files to the cache folder
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    for file in os.listdir(temp_dir):
        if file.endswith(".jpg"):
            shutil.move(os.path.join(temp_dir, file), os.path.join(cache_dir, file))

    shutil.rmtree(temp_dir)

    return filename
