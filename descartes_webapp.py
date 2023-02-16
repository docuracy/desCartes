'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''

import logging
from flask import Flask, request, jsonify
import uuid
import os
import shutil
import datetime
import rasterio
import numpy as np
import cv2
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
# from image_processing import skeleton_contours, erase_matches, erase_areas
from road_contours import road_contours
import base64
import re

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
            args = {k: v for k, v in request.args.items() if k != 'bounds'}
            bounds = request.args.get('bounds')
            if bounds:
                EXTENT = bounds.split(",")
                EXTENT = [float(x) for x in EXTENT]
                
                LOCATION_NAME = re.sub(r'https://|[{}/.]', '-', RASTER_TILE_URL+ '-' + bounds).replace(',', '_').strip('-')
                OUTPUTDIR = './output/' + LOCATION_NAME + '/'
                GEOTIFF_NAME = LOCATION_NAME + '.tiff'
                
                if os.path.exists(OUTPUTDIR + GEOTIFF_NAME):
                    mapfile = OUTPUTDIR + GEOTIFF_NAME
                else:
                    mapfile = create_geotiff (RASTER_TILE_URL, OUTPUTDIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
                
                _, _, base64_images, vector_json = road_contours(mapfile, **args)
                
                # Clean up output directory
                now = datetime.datetime.now()
                cutoff = now - datetime.timedelta(hours=8)
                for item in os.listdir('./output/'):
                    path = os.path.join('./output/', item)
                    if os.path.isdir(path) and datetime.datetime.fromtimestamp(os.path.getctime(path)) < cutoff:
                        shutil.rmtree(path)
                        
                return jsonify({"base64_images": base64_images, "GeoPackage": vector_json})
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
    handler = logging.FileHandler('error.log')
    handler.setLevel(logging.ERROR)
    app.logger.addHandler(handler)
    app.run(debug=True, host='0.0.0.0')

