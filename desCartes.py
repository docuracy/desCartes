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

NEXT DEVELOPMENT STEPS: See https://github.com/docuracy/desCartes/issues

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
from pickle import TRUE

#####################
## USER VARIABLES  ##
#####################

# A simple way to get the extent coordinates is to open a Google map in a browser,
# then right-click on the south-west corner of the area of interest. Then click on 
# the displayed coordinates and then paste them below. Repeat for the north-east corner.
EXTENT_SOUTHWEST_LAT, EXTENT_SOUTHWEST_LNG = 51.960551, -1.744574
EXTENT_NORTHEAST_LAT, EXTENT_NORTHEAST_LNG = 51.965317, -1.740072

## The location name will be used to name the directory where files are stored.
## If a geotiff already exist in this directory, it will be re-used, and the coordinates given above ignored.
LOCATION_NAME = 'longborough'
# LOCATION_NAME = 'tormarton'

## Uncomment one of these methods, or create your own in the IMAGE PROCESSING CALLS section.
## Any name you type here will be used in creating a filename, so avoid funky characters.
# METHOD = 'candidate_areas'
METHOD = 'original'
# METHOD = 'development'

RASTER_TILE_KEY = 'ySlCyGP2kmmfm9Dgtiqj' # TO USE THE URL GIVEN BELOW, GET YOUR OWN KEY FROM https://cloud.maptiler.com/account/keys/
RASTER_TILE_URL = 'https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=' + RASTER_TILE_KEY
RASTER_TILE_ZOOM = 17

## The ROADFILE must contain LineStrings only, reprojected if necessary to EPSG:4326 (WGS84)
## It should be placed in the DATADIR defined below.
## The file used here is too large to store on GitHub. It can be extracted from data downloadable from https://beta.ordnancesurvey.co.uk/products/os-open-roads
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

SHOW_IMAGES = True

######################
## SYSTEM VARIABLES ##
######################

# Get the current date and time for use in output filenames
start_time = datetime.datetime.now()
timestamp = start_time.strftime("%Y-%m-%d_%H-%M-%S")
FILESTAMP = "_{}_{}.".format(METHOD,timestamp)

EXTENT = [EXTENT_SOUTHWEST_LNG, EXTENT_SOUTHWEST_LAT, EXTENT_NORTHEAST_LNG, EXTENT_NORTHEAST_LAT]

######################
## OPEN/CREATE MAPS ##
######################
   
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
    # cv2.waitKey(0)

################################
## IMAGE PROCESSING FUNCTIONS ##
################################

def skeleton_uint8(img):
    img = img > 0
    img = skeletonize(img)
    return (img * 255).astype(np.uint8)

window = 0 # Counter for imshow windows to prevent overwriting
def erase_areas(image, 
                factor, 
                closed = False, 
                black = False, 
                circles = False, 
                blobs = False, 
                contours = True, 
                subtract = False,
                aspect_ratio_max = .15,
                contour_area_min = 2 * MIN_ROAD_WIDTH * MAX_ROAD_WIDTH,
                contour_width_max = 3 * MAX_ROAD_WIDTH,
                convexity_min = .4,
                shading = False
                ):
    global window, OUTPUTDIR
    colour = 'black' if black else 'white'
    shading = 1 if False else -1
    form = 'shapes' if contours else 'areas'
    erasure = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    image = cv2.bitwise_not(image) if (black and not circles and not blobs) else image
    size = factor * (MIN_ROAD_WIDTH ** 2) if (contours and not circles and not blobs) else int(factor)
    if circles: # Used for removing, for example, dot shading (not very effective!)
        form = 'circles'
        r = factor
        size = (2*r+4, 2*r+4)
        template = np.ones(size, dtype=np.uint8)
        cv2.circle(template, (r+2,r+2), r, (0,0,0), -1)
        res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        # Threshold the result to find the locations where the image matches the kernel
        loc = np.where(res >= 0.6)
        # Draw circles of 8px diameter at the matching locations
        for pt in zip(*loc[::-1]):
            cv2.circle(image, (pt[0] + r+2, pt[1] + r+2), r, (255, 255, 255), -1)   
            cv2.circle(erasure, (pt[0] + r+2, pt[1] + r+2), r, (0, 0, 255), shading)   
    elif blobs:
        form = 'blobs'
        params = cv2.SimpleBlobDetector_Params()
        params.filterByColor =True
        params.blobColor = 0 if black == True else 1
        params.filterByCircularity = True
        params.maxCircularity = 1
        params.filterByArea = True
        params.maxArea = size
        detector = cv2.SimpleBlobDetector_create(params)
        keypoints = detector.detect(image)
        for kp in keypoints:
            x, y = int(kp.pt[0]), int(kp.pt[1])
            r = int(kp.size / 2)
            cv2.circle(image, (x, y), r, (255, 255, 255), -1)
            cv2.circle(erasure, (x, y), r, (0, 0, 255), shading)                    
    elif contours:
        contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if shading:
            contours = sorted(contours, key=cv2.contourArea, reverse=True)
        for contour in contours: 
            # Calculate areas of contour and its convex hull
            contour_area = cv2.contourArea(contour)
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            if hull_area == 0 or contour_area == 0:
                cv2.drawContours(erasure, [contour], -1, (0, 255, 255), shading)
                continue # Reject contour
            convexity = contour_area / hull_area

            # Calculate aspect ratio
            width, height = cv2.minAreaRect(contour)[1]
            if width == 0 or height == 0:
                cv2.drawContours(erasure, [contour], -1, (0, 255, 255), shading)
                continue # Reject contour
            else:
                aspect_ratio = min(width, height) / max(width, height)

            if aspect_ratio <= aspect_ratio_max and contour_area >= contour_area_min and min(width, height) <= contour_width_max:
                cv2.drawContours(erasure, [contour], -1, (0, 255, 0), shading) # Try not to erase road sections
            elif convexity >= convexity_min or closed == False: 
                cv2.drawContours(image, [contour], 0, (0, 0, 0), -1)
                cv2.drawContours(erasure, [contour], -1, (255, 255, 0), shading)
            else:
                cv2.drawContours(erasure, [contour], -1, (0, 0, 255), shading)
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        mask = image
        eroded_image = cv2.erode(image, kernel, iterations=1)
        dilated_image = cv2.dilate(eroded_image, kernel, iterations=1)
        image = cv2.subtract(image, dilated_image) if subtract else dilated_image
        mask = mask != image
        erasure[mask] = [0, 0, 255]
    image = cv2.bitwise_not(image) if (black and not circles and not blobs) else image
    message = 'Removed ' + colour + ' ' + form + ' (size ' + str(size) + ')'
    print(message)

    if SHOW_IMAGES:
        cv2.imshow(message + ' [' + str(window) + ']', erasure)
        cv2.imwrite(os.path.join(OUTPUTDIR, message + ' ' + str(window) + '.png'), erasure)
        cv2.waitKey(0)
        window += 1

    return image

############################
## IMAGE PROCESSING CALLS ##
############################

print('Image processing: '+METHOD)
match METHOD:
    
    case 'candidate_areas': # Attempts to filter roads from image in just two calls to the erase_areas function
        result_binary = erase_areas(result_binary, MAX_ROAD_WIDTH ** 2, blobs = True, black = True) # Attempts to remove circular markers from roadways on GB OS maps
        result_binary = erase_areas(result_binary, 
            factor = 2 * MAX_ROAD_WIDTH / MIN_ROAD_WIDTH, 
            contour_width_max = 3 * MAX_ROAD_WIDTH, 
            convexity_min = .5, 
            closed = True,
            shading = True)
    
    case 'original':
        # Testing a range of parameters that might be useful for machine learning.
        # No decent solution yet found for removing areas of woodland from GB OS maps - see longborough example.
        result_binary = erase_areas(result_binary, MAX_ROAD_WIDTH ** 2, blobs = True, black = True) # Attempts to remove circular markers from roadways on GB OS maps
        result_binary = erase_areas(result_binary, 2, contours = False) # Erase white noise
        result_binary = erase_areas(result_binary, 500, closed = True) # Erase white shapes
        # result_binary = erase_areas(result_binary, 2, contours = False, black = True) # Erase black dots
        # result_binary = erase_areas(result_binary, 50, closed = True, black = True) # Erase black shapes
        # result_binary = erase_areas(result_binary, 120, closed = True, black = True) # Erase black shapes
        # result_binary = erase_areas(result_binary, 200, black = True) # Erase black shapes
        result_binary = erase_areas(result_binary, 2 * MAX_ROAD_WIDTH, contours = False, subtract = True) # Erase large white areas
        # result_binary = erase_areas(result_binary, 500, closed = True) # Erase white shapes
        # result_binary = erase_areas(result_binary, 1.5 * MAX_ROAD_WIDTH, contours = False, subtract = True) # Erase large white areas
        result_binary = erase_areas(result_binary, 2/3 * MIN_ROAD_WIDTH, contours = False) # Erase narrow white areas
        result_binary = erase_areas(result_binary, 2000, closed = True) # Erase white shapes
        result_binary = erase_areas(result_binary, 3, contours = False) # Erase white noise
        
    case _: # Default 
        result_binary = erase_areas(result_binary, MAX_ROAD_WIDTH ** 2, blobs = True, black = True) # Attempts to remove circular markers from roadways on GB OS maps
        
# Skeletonize the binary image, find contours, and convert to LineStrings
print('Skeletonize the binary image and find contours ...')    
skeleton = skeleton_uint8(result_binary)

# Attempt to bridge gaps in skeleton by dilation and re-skeletonization
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15,15))
skeleton_dilated = cv2.dilate(skeleton, kernel, iterations=1)
if SHOW_IMAGES:
    cv2.imshow('Dilated Skeleton', skeleton_dilated)
    cv2.waitKey(0) 
skeleton = skeleton_uint8(skeleton_dilated)

#######################
## VECTOR PROCESSING ##
#######################

contours, _ = cv2.findContours(skeleton, cv2.RETR_LIST , cv2.CHAIN_APPROX_NONE)

if SHOW_IMAGES:
    plt.imshow(skeleton, cmap='gray')
    plt.show()
    raster_image_contours = raster_image_gray.copy()
    raster_image_contours = cv2.cvtColor(raster_image_contours, cv2.COLOR_GRAY2BGR)
    cv2.drawContours(raster_image_contours, contours, -1, (0,0,255), 3)
    cv2.imshow("Image with Contours", raster_image_contours)
    cv2.imwrite(os.path.join(OUTPUTDIR, 'Image with contours.png'), raster_image_contours)
    cv2.waitKey(0)

print('Convert to LineStrings ...')
linestrings = contours_to_linestrings(contours, tolerance = 2, angle_threshold = 80)

# Score sample points from LineStrings based on structural_similarity to roads and proximity to modern roads
print('Scoring '+str(len(linestrings))+' LineStrings ...')

# Open the modern roads shapefile and read in the LineStrings
modern_roads = gpd.read_file(OUTPUTDIR + 'OS_Open_Roads_LineStrings_WGS84.shp')

roadscores, modern_linklines = score_linestrings(linestrings, TEMPLATE_SAMPLE, raster_image_gray, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, modern_roads, raster.transform, MAX_MODERN_OFFSET)
save_shapefile(linestrings, raster.transform, raster.meta, OUTPUTDIR+'candidate_paths'+FILESTAMP+'shp', roadscores, modern_linklines)
linestrings, roadscores = merge_groups(linestrings, roadscores, MAX_GAP_CLOSURE, modern_roads, raster.transform, FILTER_SCORE)
save_shapefile(linestrings, raster.transform, raster.meta, OUTPUTDIR+'selected_paths'+FILESTAMP+'shp', roadscores)

##########
## CODA ##
##########

elapsed_time = datetime.datetime.now() - start_time
elapsed_time_seconds = elapsed_time.total_seconds()
elapsed_time_time = datetime.time(hour=int(elapsed_time_seconds // 3600), minute=int((elapsed_time_seconds % 3600) // 60), second=int(elapsed_time_seconds % 60))
print("Finished. Total execution time: " + elapsed_time_time.strftime("%H:%M:%S"))
