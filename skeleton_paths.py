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

DATADIR = './data/'
OUTPUTDIR = './output/'
GEOTIFF_NAME = 'tormarton.tiff'
ALPHA = 30 # Used to impose straightness on extracted paths. Maximum angle (in degrees) for road deflection within BACKSTEPS pixels
BACKSTEPS = 20 # Must be 5 or more
MINLENGTH = 40
TOLERANCE = 1
TEMPLATE_SAMPLE = 10  # pixel distance between sample points to test for each candidate LineString
MATCH_SCORE = .4 # Minimum pass score for structural_similarity in LineString filter

### TO DO: Check the template and filtering process, which is not yet good.
### Are the templates properly orientated?
### MATCH_SCORE should be determined programmatically using KMeans

SHOW_IMAGES = False

# Get the current date and time for use in output filenames
start_time = datetime.datetime.now()
timestamp = start_time.strftime("%Y-%m-%d_%H-%M-%S")
FILESTAMP = "_{}-{}-{}-{}-{}-{}_{}.".format(ALPHA,BACKSTEPS,MINLENGTH,TOLERANCE,TEMPLATE_SAMPLE,MATCH_SCORE,timestamp)

GEOTIFF = DATADIR+GEOTIFF_NAME

# Open the geotiff using rasterio
with rasterio.open(GEOTIFF) as raster:
    raster_image = raster.read()
    
raster_image_gray = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_BGR2GRAY)
## TO DO: detect and set threshold programmatically
_, result_binary = cv2.threshold(raster_image_gray, 200, 255, cv2.THRESH_BINARY)

# Erode the image to remove shading, which is typically 2px black dots, 2px apart (specific to OSGB maps c.1900)
kernel = np.ones((4,4), np.uint8)
result_binary = cv2.erode(result_binary, kernel, iterations=1)
    
result_binary = result_binary > 0

# Skeletonize the binary image, find contours, and convert to LineStrings
print('Skeletonize the binary image and find contours ...')
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
    # Get the image dimensions
    height, width = raster_image_contours.shape[:2]
    # Scale the image
    raster_image_contours = cv2.resize(raster_image_contours, (width*2, height*2), interpolation = cv2.INTER_LINEAR)
    cv2.imshow("Image with Contours", raster_image_contours)
    cv2.waitKey(0)
    
# if SHOW_IMAGES:
    # print(linestrings)
    #Save the LineStrings to a shapefile
    # print('Save the '+str(len(linestrings))+' LineStrings to a shapefile ...')
    # save_shapefile(linestrings, raster.transform, raster.meta, OUTPUTDIR+'skeleton_paths'+FILESTAMP+'shp')

# Filter sample points from LineStrings based on structural_similarity to roads
print('Scoring '+str(len(linestrings))+' LineStrings ...')
roadscores = score_linestrings(linestrings, TEMPLATE_SAMPLE, raster_image_gray)
# TO DO: filter based on scores and KMeans
save_shapefile(linestrings, raster.transform, raster.meta, OUTPUTDIR+'scored_paths'+FILESTAMP+'shp',roadscores)

# Find paths to close gaps in LineStrings
## (TO DO)

elapsed_time = datetime.datetime.now() - start_time
elapsed_time_seconds = elapsed_time.total_seconds()
elapsed_time_time = datetime.time(hour=int(elapsed_time_seconds // 3600), minute=int((elapsed_time_seconds % 3600) // 60), second=int(elapsed_time_seconds % 60))
print("Finished. Total execution time: " + elapsed_time_time.strftime("%H:%M:%S"))
