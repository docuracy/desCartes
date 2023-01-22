# -*- coding: utf-8 -*-
"""

@author: Stephen Gadd, Docuracy Ltd, UK

"""

######################################################################################
"""
NEXT DEVELOPMENT STEPS



"""
import rasterio
import numpy as np
import cv2
import datetime
from skimage.morphology import skeletonize
from shapely.geometry import LineString
from save_shapefile import save_shapefile
import matplotlib.pyplot as plt
import math
import random
from contours_to_linestrings import contours_to_linestrings
from road_templates import score_linestrings
from tiles_to_tiff import create_geotiff
from extract_modern_roads import extract_modern_roads

EXTENT = [-1.333021,53.918548,-1.313999,53.925807]
LOCATION_NAME = 'walton'
RASTER_TILE_URL = 'https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=U2vLM8EbXurAd3Gq6C45'
RASTER_TILE_ZOOM = 17

ROADFILE = 'OS_Open_Roads_LineStrings_WGS84.gpkg'

FIELD_MIN_DIMENSION = 50

DATADIR = './data/'
OUTPUTDIR = './output/' + LOCATION_NAME + '/'
GEOTIFF_NAME = LOCATION_NAME + '.tiff'
TEMPLATE_SAMPLE = 10  # pixel distance between sample points to test for each candidate LineString
MATCH_SCORE = .4 # Minimum pass score for structural_similarity in LineString filter

NEW_MAP = False
SHOW_IMAGES = True

# Get the current date and time for use in output filenames
start_time = datetime.datetime.now()
timestamp = start_time.strftime("%Y-%m-%d_%H-%M-%S")
FILESTAMP = "_{}.".format(timestamp)
   
if NEW_MAP:
    mapfile = create_geotiff (RASTER_TILE_URL, OUTPUTDIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
    extract_modern_roads(DATADIR, mapfile, OUTPUTDIR, ROADFILE, LOCATION_NAME)
else:
    mapfile = OUTPUTDIR + GEOTIFF_NAME

# Open the geotiff using rasterio
with rasterio.open(mapfile) as raster:
    raster_image = raster.read()
    
raster_image_gray = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_BGR2GRAY)
## TO DO: detect and set threshold programmatically
_, result_binary = cv2.threshold(raster_image_gray, 200, 255, cv2.THRESH_BINARY)

# Erode the image to remove shading, which is typically 2px black dots, 2px apart (specific to OSGB maps c.1900)
kernel = np.ones((4,4), np.uint8)
result_binary = cv2.erode(result_binary, kernel, iterations=1)

# Now remove large areas such as fields
print('Removing large white areas ...')    
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
eroded_image = cv2.erode(result_binary, kernel)
diff_image = cv2.subtract(result_binary, eroded_image)
result_binary = cv2.add(diff_image, eroded_image)

cv2.imshow("Image with Contours", result_binary)
cv2.waitKey(0)
    
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

# Filter sample points from LineStrings based on structural_similarity to roads
print('Scoring '+str(len(linestrings))+' LineStrings ...')
roadscores = score_linestrings(linestrings, TEMPLATE_SAMPLE, raster_image_gray)
# TO DO: filter based on scores and KMeans; boost scores based on similarity to modern roads
save_shapefile(linestrings, raster.transform, raster.meta, OUTPUTDIR+'scored_paths'+FILESTAMP+'shp',roadscores)

# Find paths to close gaps in LineStrings
## (TO DO)

elapsed_time = datetime.datetime.now() - start_time
elapsed_time_seconds = elapsed_time.total_seconds()
elapsed_time_time = datetime.time(hour=int(elapsed_time_seconds // 3600), minute=int((elapsed_time_seconds % 3600) // 60), second=int(elapsed_time_seconds % 60))
print("Finished. Total execution time: " + elapsed_time_time.strftime("%H:%M:%S"))
