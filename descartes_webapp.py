'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''

import logging
from flask import Flask, request, jsonify
import os
import shutil
import datetime
from tiles_to_tiff import create_geotiff
from extract_modern_roads import extract_modern_roads
from desCartes import desCartes
import re

DATADIR = './data/'

app = Flask(__name__)

@app.route("/", methods=['POST'])
def get_desCartes():
    try:
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
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    handler = logging.FileHandler('error.log')
    handler.setLevel(logging.ERROR)
    app.logger.addHandler(handler)
    app.run(debug=True, host='0.0.0.0')

