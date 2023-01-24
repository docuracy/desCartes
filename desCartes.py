# -*- coding: utf-8 -*-
"""

@author: Stephen Gadd, Docuracy Ltd, UK

"""

######################################################################################
"""
NEXT DEVELOPMENT STEPS



"""
import os
import rasterio
import numpy as np
import cv2
import datetime
from skimage.morphology import skeletonize
import shapely.geometry
# from shapely.geometry import LineString
from save_shapefile import save_shapefile
import matplotlib.pyplot as plt
import math
import random
from contours_to_linestrings import contours_to_linestrings
from road_templates import score_linestrings
from tiles_to_tiff import create_geotiff
from extract_modern_roads import extract_modern_roads
import geopandas as gpd

EXTENT = [-4.110772,50.640997,-4.088993,50.650038]
LOCATION_NAME = 'lydford'
RASTER_TILE_URL = 'https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=U2vLM8EbXurAd3Gq6C45'
RASTER_TILE_ZOOM = 17

ROADFILE = 'OS_Open_Roads_LineStrings_WGS84.gpkg'


MAX_ROAD_WIDTH = 15  # Pixel width of road between border lines. Should be an odd number
MIN_ROAD_WIDTH = 3 # Should be an odd number

DATADIR = './data/'
OUTPUTDIR = './output/' + LOCATION_NAME + '/'
GEOTIFF_NAME = LOCATION_NAME + '.tiff'
TEMPLATE_SAMPLE = 10  # pixel distance between sample points to test for each candidate LineString
MATCH_SCORE = .4 # Minimum pass score for structural_similarity in LineString filter

SHOW_IMAGES = False

# Get the current date and time for use in output filenames
start_time = datetime.datetime.now()
timestamp = start_time.strftime("%Y-%m-%d_%H-%M-%S")
FILESTAMP = "_{}.".format(timestamp)
   
if os.path.exists(OUTPUTDIR + GEOTIFF_NAME):
    mapfile = OUTPUTDIR + GEOTIFF_NAME
else:
    mapfile = create_geotiff (RASTER_TILE_URL, OUTPUTDIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
    extract_modern_roads(DATADIR, mapfile, OUTPUTDIR, ROADFILE, LOCATION_NAME)

# Open the geotiff using rasterio
with rasterio.open(mapfile) as raster:
    raster_image = raster.read()
    
raster_image_gray = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_BGR2GRAY)
## TO DO: detect and set threshold programmatically
_, result_binary = cv2.threshold(raster_image_gray, 200, 255, cv2.THRESH_BINARY)

if SHOW_IMAGES:
    cv2.imshow("Original raster binary", result_binary)
    cv2.waitKey(0)

# # Now remove freestanding black dots which form boundary lines, typically 8px diameter
# r = 4
# size = (2*r+5, 2*r+5)
# template = np.zeros(size, dtype=np.uint8)
# cv2.circle(template, (r+2,r+2), r, (255,255,255), -1)
# cv2.circle(template, (r+2,r+2), r+2, (0,0,0), 1)
# template = cv2.bitwise_xor(template, np.ones(size, dtype=np.uint8)*255)
# res = cv2.matchTemplate(result_binary, template, cv2.TM_CCOEFF_NORMED)
# # Threshold the result to find the locations where the image matches the kernel
# loc = np.where(res >= 0.6)
# # Draw circles of 8px diameter at the matching locations
# for pt in zip(*loc[::-1]):
#     cv2.circle(result_binary, (pt[0] + r+2, pt[1] + r+2), r, (255, 255, 255), -1)
#
# if SHOW_IMAGES:
#     cv2.imshow("Removed black dots", result_binary)
#     cv2.waitKey(0)

# Find small black shapes in the image and turn them white
print('Removing small black shapes ...')    
MIN_AREA = 20 * (MIN_ROAD_WIDTH ** 2)
result_binary = cv2.bitwise_not(result_binary)
contours, _ = cv2.findContours(result_binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
for contour in contours:
    if cv2.isContourConvex(contour): # Check if the contour is closed
        if cv2.contourArea(contour) < MIN_AREA:
            cv2.drawContours(result_binary, [contour], 0, (0, 0, 0), -1)
result_binary = cv2.bitwise_not(result_binary)

if SHOW_IMAGES:
    cv2.imshow("Removed small black shapes", result_binary)
    cv2.waitKey(0)

# Now remove large white areas (might be fields)
print('Removing large white areas ...')    
kernel_size = int(MAX_ROAD_WIDTH*1.5)
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
eroded_image = cv2.erode(result_binary, kernel, iterations=1)
dilated_image = cv2.dilate(eroded_image, kernel, iterations=1)
result_binary = cv2.subtract(result_binary, dilated_image)

if SHOW_IMAGES:
    cv2.imshow("Removed large white areas", result_binary)
    cv2.waitKey(0)

# Now remove narrow white areas
print('Removing narrow white areas ...')    
kernel_size = int(MIN_ROAD_WIDTH*2/3)
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
result_binary = cv2.erode(result_binary, kernel, iterations=1)
result_binary = cv2.dilate(result_binary, kernel, iterations=1)

if SHOW_IMAGES:
    cv2.imshow("Removed narrow white areas", result_binary)
    cv2.waitKey(0)

# Find small white shapes in the image and turn them black
print('Removing small white shapes ...')    
MIN_AREA = 200 * (MIN_ROAD_WIDTH ** 2)
contours, _ = cv2.findContours(result_binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
for contour in contours:
    if cv2.isContourConvex(contour): # Check if the contour is closed
        if cv2.contourArea(contour) < MIN_AREA:
            cv2.drawContours(result_binary, [contour], 0, (0, 0, 0), -1)

if SHOW_IMAGES:
    cv2.imshow("Removed small white shapes", result_binary)
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

# Score sample points from LineStrings based on structural_similarity to roads and proximity to modern roads
print('Scoring '+str(len(linestrings))+' LineStrings ...')

# Open the modern roads shapefile and read in the LineStrings
modern_roads = gpd.read_file(OUTPUTDIR + 'OS_Open_Roads_LineStrings_WGS84.shp')
# print(modern_roads['id'])
# print(modern_roads['geometry'])

roadscores = score_linestrings(linestrings, TEMPLATE_SAMPLE, raster_image_gray, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, modern_roads, raster.transform)
# TO DO: filter based on scores and KMeans; boost scores based on similarity to modern roads
save_shapefile(linestrings, raster.transform, raster.meta, OUTPUTDIR+'scored_paths'+FILESTAMP+'shp',roadscores)

# Find paths to close gaps in LineStrings
## (TO DO)

elapsed_time = datetime.datetime.now() - start_time
elapsed_time_seconds = elapsed_time.total_seconds()
elapsed_time_time = datetime.time(hour=int(elapsed_time_seconds // 3600), minute=int((elapsed_time_seconds % 3600) // 60), second=int(elapsed_time_seconds % 60))
print("Finished. Total execution time: " + elapsed_time_time.strftime("%H:%M:%S"))
