from flask import Flask, request, jsonify
import uuid
import os
import rasterio
import numpy as np
import cv2
import datetime
from skimage.morphology import skeletonize
from save_shapefile import save_shapefile
import matplotlib.pyplot as plt
import math
import geopandas as gpd
from contours_to_linestrings import contours_to_linestrings
from road_templates import score_linestrings
from tiles_to_tiff import create_geotiff
from extract_modern_roads import extract_modern_roads
from patch_linestrings import merge_groups
from pickle import TRUE
from image_processing import skeleton_contours, erase_matches, erase_areas
import base64

LOCATION_NAME = str(uuid.uuid4())
OUTPUTDIR = './output/' + LOCATION_NAME + '/'
GEOTIFF_NAME = LOCATION_NAME + '.tiff'

RASTER_TILE_KEY = 'ySlCyGP2kmmfm9Dgtiqj' # TO USE THE URL GIVEN BELOW, GET YOUR OWN KEY FROM https://cloud.maptiler.com/account/keys/
RASTER_TILE_URL = 'https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=' + RASTER_TILE_KEY
RASTER_TILE_ZOOM = 17

MAX_ROAD_WIDTH = 15  # Pixel width of road between border lines. Should be an odd number
MIN_ROAD_WIDTH = 3 # Should be an odd number

app = Flask(__name__)

@app.route("/", methods=['GET', 'POST'])
def hello():
    try:
        if request.method == 'GET':
            bounds = request.args.get('bounds')
            if bounds:
                EXTENT = bounds.split(",")
                EXTENT = [float(x) for x in EXTENT]
                mapfile = create_geotiff (RASTER_TILE_URL, OUTPUTDIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
                
                # Open the geotiff using rasterio
                with rasterio.open(mapfile) as raster:
                    raster_image = raster.read()
                    
                raster_image_gray = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_BGR2GRAY)
                _, result_binary = cv2.threshold(raster_image_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                
                result_binary = erase_areas(result_binary, raster_image_gray, factor = MAX_ROAD_WIDTH ** 2, blobs = True, black = True, SHOW_IMAGES = False, OUTPUTDIR = OUTPUTDIR) # Attempts to remove circular markers from roadways on GB OS maps
                result_binary = erase_matches(raster_image_gray, result_binary, './data/templates', 'tree-broadleaf.png', SHOW_IMAGES = False, OUTPUTDIR = OUTPUTDIR)
                result_binary = erase_matches(raster_image_gray, result_binary, './data/templates', 'tree-conifer.png', threshold=0.7, SHOW_IMAGES = False, OUTPUTDIR = OUTPUTDIR)
                result_binary = erase_areas(result_binary, raster_image_gray, 
                    factor = 2 * MAX_ROAD_WIDTH / MIN_ROAD_WIDTH, 
                    contour_width_max = 3 * MAX_ROAD_WIDTH, 
                    convexity_min = .5, 
                    closed = True,
                    shading = True,
                    thresholds = [.7,.65], 
                    SHOW_IMAGES = False, 
                    OUTPUTDIR = OUTPUTDIR
                    )   
                contours = skeleton_contours(result_binary, raster_image_gray, SHOW_IMAGES = False)
                raster_image_contours = cv2.cvtColor(raster_image_gray, cv2.COLOR_GRAY2BGR)
                cv2.drawContours(raster_image_contours, contours, -1, (0,0,255), 3)   
                encoded_image = base64.b64encode(cv2.imencode('.jpg', raster_image_contours)[1]).decode("utf-8")
                # encoded_image = base64.b64encode(cv2.imencode('.jpg', result_binary)[1]).decode("utf-8")
                return jsonify({"base64_image": encoded_image})
            else:
                return jsonify({"message": "No bounds found in the request."})
        else:
            # POST requests are not properly handled by nginx/Apache on IONOS Plesk system
            msg = request.get_json().get('msg')
            if msg:
                return jsonify({"message": msg})
            else:
                return jsonify({"message": "POST desCartes!"})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(host='0.0.0.0')

