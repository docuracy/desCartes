import urllib.request
import os
import glob
import shutil
from tile_convert import bbox_to_xyz, tile_edges
from osgeo import gdal
import pyproj as proj

temp_dir = os.path.join(os.path.dirname(__file__), 'temp')

def fetch_tile(x, y, z, tile_source):
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


def merge_tiles(input_pattern, output_path):
    vrt_path = temp_dir + "/tiles.vrt"
    gdal.BuildVRT(vrt_path, glob.glob(input_pattern))
    gdal.Translate(output_path, vrt_path)


def georeference_raster_tile(x, y, z, path):
    bounds = tile_edges(x, y, z)
    
    #crs_wgs = proj.Proj(init='epsg:4326') # WGS84 geographic
    #crs_bng = proj.Proj(init='epsg:27700') # British National Grid
    #bounds[0],bounds[1] = proj.transform(crs_wgs, crs_bng, bounds[0], bounds[1])
    #bounds[2],bounds[3] = proj.transform(crs_wgs, crs_bng, bounds[2], bounds[3])
    
    gdal.Translate(os.path.join(temp_dir, f'{temp_dir}/{x}_{y}_{z}.tif'),
                   path,
                   outputSRS='EPSG:4326',
                   #outputSRS='EPSG:27700',
                   outputBounds=bounds)

def create_geotiff(tile_source, output_dir, geotiff_name, bounding_box, zoom): 
    lon_min, lat_min, lon_max, lat_max = bounding_box

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
                png_path = fetch_tile(x, y, zoom, tile_source)
                print(f"{x},{y},{tile_source} fetched")
                georeference_raster_tile(x, y, zoom, png_path)
            except OSError:
                print(f"Error, failed to get {x},{y}")
                pass

    print("Resolving and georeferencing of raster tiles complete")

    print("Merging tiles")
    filename = output_dir + '/' + geotiff_name
    merge_tiles(temp_dir + '/*.tif', filename)
    print("Merge complete")
    
    # input_raster = gdal.Open(WGS84_filename)
    # output_raster = output_dir + '/' + geotiff_name
    # kwargs = {'dstAlpha': True}
    # warp = gdal.Warp(output_raster,input_raster,dstSRS='EPSG:27700',**kwargs)
    # warp = None # Closes the files

    shutil.rmtree(temp_dir)
    
    return filename
    