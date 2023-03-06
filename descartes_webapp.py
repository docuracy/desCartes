'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''

import logging
from logging.handlers import RotatingFileHandler
import sys
from flask import Flask, request, jsonify
import os
import shutil
import datetime
from tiles_to_tiff import create_geotiff
from extract_modern_roads import extract_modern_roads
from desCartes import desCartes

DATADIR = './data/'

app = Flask(__name__)

# create the logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# create the formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# create the file handler
file_handler = RotatingFileHandler('desCartes.log', maxBytes=100000, backupCount=10)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# create the stream handler
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.DEBUG)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# redirect print statements to the logger
class PrintToLogger:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level

    def write(self, message):
        if message.strip():
            self.logger.log(self.level, message.strip())

sys.stdout = PrintToLogger(logger, logging.INFO)
sys.stderr = PrintToLogger(logger, logging.ERROR)

@app.route("/", methods=['POST'])
def get_desCartes():
    try:
        logger.info("Starting get_desCartes function")
        
        args = {k: v for k, v in request.form.items() if k not in ['viewID', 'bounds', 'url', 'zoom', 'modern_roads', 'default_values_dropdown']}
        bounds = request.form.get('bounds')
        if bounds:
            EXTENT = bounds.split(",")
            EXTENT = [float(x) for x in EXTENT]
    
            RASTER_TILE_URL = request.form.get('url')
            RASTER_TILE_ZOOM = int(request.form.get('zoom'))
            MODERN_ROADFILE = request.form.get('modern_roads')
            VIEW_ID = request.form.get('viewID')
    
            OUTPUTDIR = './output/' + VIEW_ID + '/'
            GEOTIFF_NAME = 'geo.tiff'
    
            if not os.path.exists(OUTPUTDIR + GEOTIFF_NAME):
                create_geotiff(RASTER_TILE_URL, OUTPUTDIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
                extract_modern_roads(DATADIR, OUTPUTDIR, MODERN_ROADFILE, VIEW_ID, EXTENT)
    
            _, _, result_images, message = desCartes(OUTPUTDIR, **args)
    
            logger.debug(f"desCartes function completed with result_images: {result_images}")
    
            # Clean up output directory
            now = datetime.datetime.now()
            cutoff = now - datetime.timedelta(hours=8)
            for item in os.listdir('./output/'):
                path = os.path.join('./output/', item)
                if os.path.isdir(path) and datetime.datetime.fromtimestamp(os.path.getctime(path)) < cutoff:
                    shutil.rmtree(path)
    
            return jsonify({"result_images": result_images, "GeoPackage": OUTPUTDIR + 'desCartes.gpkg', "message": message})
        else:
            return jsonify({"message": "No bounds found in the request."})
            
    except Exception as e:
        tb = sys.exc_info()[2]
        logger.error(f"Error: {e}, line: {tb.tb_lineno}")
        return jsonify({"error": f"Error: {e}, line: {tb.tb_lineno}"})

