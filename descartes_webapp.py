'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''

import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify
import os
import shutil
import datetime
from tiles_to_tiff import create_geotiff
from extract_modern_roads import extract_modern_roads
from desCartes import desCartes

DATADIR = './data/'

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
handler = RotatingFileHandler('desCartes.log', maxBytes=100000, backupCount=10)
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

@app.route("/", methods=['POST'])
def get_desCartes():
    try:
        app.logger.info("Starting get_desCartes function")
        
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
    
            app.logger.debug(f"desCartes function completed with result_images: {result_images}")
    
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
        app.logger.error(str(e))
        return jsonify({"error": str(e)})

