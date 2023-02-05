from flask import Flask, request, jsonify
from tiles_to_tiff import create_geotiff
import uuid

LOCATION_NAME = str(uuid.uuid4())
OUTPUTDIR = './output/' + LOCATION_NAME + '/'
GEOTIFF_NAME = LOCATION_NAME + '.tiff'

RASTER_TILE_KEY = 'ySlCyGP2kmmfm9Dgtiqj' # TO USE THE URL GIVEN BELOW, GET YOUR OWN KEY FROM https://cloud.maptiler.com/account/keys/
RASTER_TILE_URL = 'https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=' + RASTER_TILE_KEY
RASTER_TILE_ZOOM = 17

app = Flask(__name__)

@app.route("/", methods=['GET', 'POST'])
def hello():
    if request.method == 'GET':
        bounds = request.args.get('bounds')
        if bounds:
            EXTENT = bounds.split(",")
            EXTENT = [float(x) for x in EXTENT]
            mapfile = create_geotiff (RASTER_TILE_URL, OUTPUTDIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
            return jsonify({"mapfilename": mapfile})
        else:
            return jsonify({"message": "No bounds found in the request."})
    else:
        # POST requests are not properly handled by nginx/Apache on IONOS Plesk system
        msg = request.get_json().get('msg')
        if msg:
            return jsonify({"message": msg})
        else:
            return jsonify({"message": "POST desCartes!"})

if __name__ == "__main__":
    app.run(host='0.0.0.0')

