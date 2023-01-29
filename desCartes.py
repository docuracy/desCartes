'''
@author: Stephen Gadd, Docuracy Ltd, UK

desCartes recognises roads on old maps, and converts them to vector lines that can be 
used in GIS applications and historical transport network analysis.

For any given map extent (bounding coordinates), desCartes first generates a a 
georeferenced map image (geotiff), and then processes the image to extract candidate 
road lines. These lines are then tested for similarity against an idealised road template, 
and matched by proximity and orientation to modern road vectors. Gaps in the road lines 
are then filled (and junctions made) where appropriate, and each line is assigned a 
certainty score and (where possible) the id of the matching modern road segment.

desCartes is pre-configured for use with the National Library of Scotland's 19th-century 
6":1 mile GB Ordnance Survey map tiles served by MapTiler Cloud, and with the modern 
Ordnance Survey Open Roads vector dataset, but might be adapted to suit other maps.

NEXT DEVELOPMENT STEPS

Join fragments that share a modernity id.
Snap singular endpoints to other endpoints if nearby and merge to single LineString, 
otherwise add intermediate point to intersected line and move original endpoint to 
that point.

Try on OS drawings via LoL XYZ tiles.
Try also https://commons.wikimedia.org/wiki/Gallery:Ordnance_Survey_1st_series_1:63360

'''
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

EXTENT = [-2.339902,51.500157,-2.329067,51.512027]
LOCATION_NAME = 'tormarton'
RASTER_TILE_URL = 'https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=U2vLM8EbXurAd3Gq6C45'
RASTER_TILE_ZOOM = 17

ROADFILE = 'OS_Open_Roads_LineStrings_WGS84.gpkg'
MAX_MODERN_OFFSET = 300 # Maximum allowable offset (degrees*1000, approximately metres)
MAX_GAP_CLOSURE = 3000 / 1000000 # Maximum gap to be closed on matched modernity_id (degrees: approximately metres / 1000000)

MAX_ROAD_WIDTH = 15  # Pixel width of road between border lines. Should be an odd number
MIN_ROAD_WIDTH = 3 # Should be an odd number

DATADIR = './data/'
OUTPUTDIR = './output/' + LOCATION_NAME + '/'
GEOTIFF_NAME = LOCATION_NAME + '.tiff'
TEMPLATE_SAMPLE = 10  # pixel distance between sample points to test for each candidate LineString
MATCH_SCORE = .4 # Minimum pass score for structural_similarity in LineString filter
FILTER_SCORE = 20 # Reject road candidates failing to meet this minimum score

SHOW_IMAGES = False

# Get the current date and time for use in output filenames
start_time = datetime.datetime.now()
timestamp = start_time.strftime("%Y-%m-%d_%H-%M-%S")
FILESTAMP = "_{}.".format(timestamp)
   
if os.path.exists(OUTPUTDIR + GEOTIFF_NAME):
    mapfile = OUTPUTDIR + GEOTIFF_NAME
else:
    mapfile = create_geotiff (RASTER_TILE_URL, OUTPUTDIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
    extract_modern_roads(DATADIR, mapfile, OUTPUTDIR, ROADFILE, LOCATION_NAME, EXTENT)

# Open the geotiff using rasterio
with rasterio.open(mapfile) as raster:
    raster_image = raster.read()
    
raster_image_gray = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_BGR2GRAY)
## TO DO: detect and set threshold programmatically
_, result_binary = cv2.threshold(raster_image_gray, 200, 255, cv2.THRESH_BINARY)

if SHOW_IMAGES:
    cv2.imshow("Original raster binary", result_binary)
    cv2.waitKey(0)

window = 0
def erase_areas(image, factor, closed = False, black = False, contours = True, subtract = False):
    global window
    colour = 'black' if black else 'white'
    form = 'shapes' if contours else 'areas'
    image = cv2.bitwise_not(image) if black else image
    size = factor * (MIN_ROAD_WIDTH ** 2) if contours else int(factor)
    if contours:
        contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if (cv2.isContourConvex(contour) or closed == False) and cv2.contourArea(contour) < size:
                cv2.drawContours(image, [contour], 0, (0, 0, 0), -1)
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
        eroded_image = cv2.erode(image, kernel, iterations=1)
        dilated_image = cv2.dilate(eroded_image, kernel, iterations=1)
        image = cv2.subtract(image, dilated_image) if subtract else dilated_image
    image = cv2.bitwise_not(image) if black else image
    message = 'Removed ' + colour + ' ' + form + ': size = ' + str(size)
    print(message)
    
    if SHOW_IMAGES:
        if contours:
            raster_image_contours = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            cv2.drawContours(raster_image_contours, contours, -1, (0,0,255), 1)
            cv2.imshow(message + ' [' + str(window) + ']', raster_image_contours)
        else:
            cv2.imshow(message + ' [' + str(window) + ']', image)
        cv2.waitKey(0)
        window += 1
        
    return image

## TO DO: Following line is too blunt - test shapes for squareness before erasure, perhaps by comparing shape area with the area of its convex hull
result_binary = erase_areas(result_binary, 500) # Erase white shapes
# result_binary = erase_areas(result_binary, 2/3, black = True, contours = False, subtract = True) # Erase black areas
result_binary = erase_areas(result_binary, 200, black = True) # Erase black shapes
result_binary = erase_areas(result_binary, 2 * MAX_ROAD_WIDTH, contours = False, subtract = True) # Erase large white areas
result_binary = erase_areas(result_binary, 2/3 * MIN_ROAD_WIDTH, contours = False) # Erase narrow white areas
result_binary = erase_areas(result_binary, 500) # Erase white shapes
    
# Skeletonize the binary image, find contours, and convert to LineStrings
print('Skeletonize the binary image and find contours ...')    
result_binary = result_binary > 0
skeleton = skeletonize(result_binary)
skeleton = (skeleton * 255).astype(np.uint8)
contours, _ = cv2.findContours(skeleton, cv2.RETR_EXTERNAL , cv2.CHAIN_APPROX_NONE)
print('Convert to LineStrings ...')
linestrings = contours_to_linestrings(contours, tolerance = 2, angle_threshold = 80)

if SHOW_IMAGES:
    # print(contours)
    plt.imshow(skeleton, cmap='gray')
    plt.show()
    raster_image_contours = raster_image_gray.copy()
    raster_image_contours = cv2.cvtColor(raster_image_contours, cv2.COLOR_GRAY2BGR)
    cv2.drawContours(raster_image_contours, contours, -1, (0,0,255), 1)
    cv2.imshow("Image with Contours", raster_image_contours)
    cv2.waitKey(0)

# Score sample points from LineStrings based on structural_similarity to roads and proximity to modern roads
print('Scoring '+str(len(linestrings))+' LineStrings ...')

# Open the modern roads shapefile and read in the LineStrings
modern_roads = gpd.read_file(OUTPUTDIR + 'OS_Open_Roads_LineStrings_WGS84.shp')

roadscores, modern_linklines = score_linestrings(linestrings, TEMPLATE_SAMPLE, raster_image_gray, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, modern_roads, raster.transform, MAX_MODERN_OFFSET)
save_shapefile(linestrings, raster.transform, raster.meta, OUTPUTDIR+'candidate_paths'+FILESTAMP+'shp', roadscores, modern_linklines)
linestrings, roadscores = merge_groups(linestrings, roadscores, MAX_GAP_CLOSURE, modern_roads, raster.transform, FILTER_SCORE)
save_shapefile(linestrings, raster.transform, raster.meta, OUTPUTDIR+'selected_paths'+FILESTAMP+'shp', roadscores)

elapsed_time = datetime.datetime.now() - start_time
elapsed_time_seconds = elapsed_time.total_seconds()
elapsed_time_time = datetime.time(hour=int(elapsed_time_seconds // 3600), minute=int((elapsed_time_seconds % 3600) // 60), second=int(elapsed_time_seconds % 60))
print("Finished. Total execution time: " + elapsed_time_time.strftime("%H:%M:%S"))
