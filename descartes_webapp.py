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

@app.route("/", methods=['GET', 'POST'])
def get_desCartes():
    try:
        if request.method == 'GET':
            args = {k: v for k, v in request.args.items() if k not in ['bounds', 'url', 'zoom', 'modern_roads', 'default_values_dropdown']}
            bounds = request.args.get('bounds')
            if bounds:
                EXTENT = bounds.split(",")
                EXTENT = [float(x) for x in EXTENT]
                
                RASTER_TILE_URL = request.args.get('url')
                RASTER_TILE_ZOOM = request.args.get('zoom')
                MODERN_ROADFILE = request.args.get('modern_roads')
                
                LOCATION_NAME = re.sub(r'https://|[{}/.?]', '-', RASTER_TILE_URL+ '-' + bounds).replace(',', '_').strip('-')
                OUTPUTDIR = './output/' + LOCATION_NAME + '/'
                GEOTIFF_NAME = 'geo.tiff'
                    
                if not os.path.exists(OUTPUTDIR + GEOTIFF_NAME):
                    create_geotiff (RASTER_TILE_URL, OUTPUTDIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
                    extract_modern_roads(DATADIR, OUTPUTDIR, MODERN_ROADFILE, LOCATION_NAME, EXTENT)
                
                _, _, base64_images, vector_json, message = desCartes(OUTPUTDIR, **args)
                
                # Clean up output directory
                now = datetime.datetime.now()
                cutoff = now - datetime.timedelta(hours=8)
                for item in os.listdir('./output/'):
                    path = os.path.join('./output/', item)
                    if os.path.isdir(path) and datetime.datetime.fromtimestamp(os.path.getctime(path)) < cutoff:
                        shutil.rmtree(path)
                        
                return jsonify({"base64_images": base64_images, "GeoPackage": vector_json, "message": message})
            else:
                return jsonify({"message": "No bounds found in the request."})
        else:
            # POST requests are not properly handled by nginx/Apache on IONOS Plesk system
            msg = request.get_json().get('msg')
            if msg:
                return jsonify({"message": msg})
            else:
                return jsonify({"message": "POST obsolete_code!"})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    handler = logging.FileHandler('error.log')
    handler.setLevel(logging.ERROR)
    app.logger.addHandler(handler)
    app.run(debug=True, host='0.0.0.0')

