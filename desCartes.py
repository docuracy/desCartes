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
from extract_modern_roads import extract_modern_roads, transform_linestrings
from patch_linestrings import merge_groups
from pickle import TRUE
from image_processing import skeleton_contours, erase_matches, erase_areas
import base64
from find_areas import find_areas
from road_contours import road_contours

#####################
## USER VARIABLES  ##
#####################

# A simple way to get the extent coordinates is to open a Google map in a browser,
# then right-click on the south-west corner of the area of interest. Then click on 
# the displayed coordinates and then paste them below. Repeat for the north-east corner.
EXTENT_SOUTHWEST_LAT, EXTENT_SOUTHWEST_LNG = 51.76671059545997, 0.7862768254319205,
EXTENT_NORTHEAST_LAT, EXTENT_NORTHEAST_LNG = 51.77743715016658, 0.8063655953527965

## The location name will be used to name the directory where files are stored.
## If a geotiff already exist in this directory, it will be re-used, and the coordinates given above ignored.
LOCATION_NAME = 'longborough'
# LOCATION_NAME = 'longborough-south'
# LOCATION_NAME = 'tormarton'
# LOCATION_NAME = 'tolleshunt'

## Uncomment one of these methods, or create your own in the IMAGE PROCESSING CALLS section.
## Any name you type here will be used in creating a filename, so avoid funky characters.
METHOD = 'road_contours'
# METHOD = 'progressive'
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
GEOTIFF_NAME = 'geo.tiff'
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
    extract_modern_roads(DATADIR, OUTPUTDIR, ROADFILE, LOCATION_NAME, EXTENT, shapefile = True)

# Open the geotiff using rasterio
with rasterio.open(mapfile) as raster:
    raster_image = raster.read()
    
raster_image_gray = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_BGR2GRAY)
## TO DO: detect and set threshold programmatically
# _, result_binary = cv2.threshold(raster_image_gray, 200, 255, cv2.THRESH_BINARY)
_, result_binary = cv2.threshold(raster_image_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

# if SHOW_IMAGES:
#     cv2.imshow("Original raster binary", result_binary)
    # cv2.waitKey(0)

################################
## IMAGE PROCESSING FUNCTIONS ##
################################

# def erase_matches(gray_image, binary_image, template_dir, template_filename, threshold=0.7, rotation_step = 0, SHOW_IMAGES = False):
#     template = cv2.imread(f"{template_dir}/{template_filename}", 0)
#     binarized_template = cv2.threshold(template, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
#     rows, cols = binarized_template.shape
#     border = cv2.copyMakeBorder(binarized_template, rows, rows, cols, cols, cv2.BORDER_CONSTANT, value=255)
#
#     found_matches = []
#
#     for angle in range(0, 10 if rotation_step == 0 else 360, 100 if rotation_step == 0 else rotation_step):
#         # Rotate the template image
#         rows, cols = template.shape
#         M = cv2.getRotationMatrix2D((cols + cols, rows + rows), angle, 1)
#         rotated_template = cv2.warpAffine(border, M, (cols + cols * 2, rows + rows * 2))
#         cropped_template = rotated_template[rows:rows + rows, cols:cols + cols]
#         res = cv2.matchTemplate(gray_image, cropped_template, cv2.TM_CCOEFF_NORMED)
#         # Perform template matching
#         cv2.imshow(f'Rotated template: {template_filename} - {angle}', rotated_template)
#         loc = np.where(res >= threshold)
#         found_matches.extend(list(zip(*loc[::-1])))
#
#     print(f'{len(found_matches)} {template_filename} matches found.')
#     for pt in found_matches:
#         for i in range(cropped_template.shape[0]):
#             for j in range(cropped_template.shape[1]):
#                 if cropped_template[i][j] == 0:
#                     binary_image[pt[1]+i][pt[0]+j] = 255
#
#     if SHOW_IMAGES:
#         gray_image_outlined = cv2.cvtColor(gray_image, cv2.COLOR_GRAY2BGR)
#         for pt in found_matches:
#             top_left = (pt[0], pt[1])
#             bottom_right = (pt[0] + cropped_template.shape[1], pt[1] + cropped_template.shape[0])
#             cv2.rectangle(gray_image_outlined, top_left, bottom_right, (0,0,255), 2)
#         cv2.imshow(f'Match locations: {template_filename}', gray_image_outlined)
#         cv2.imwrite(os.path.join(OUTPUTDIR, f'Match locations - {template_filename}.png'), gray_image_outlined)
#         cv2.waitKey(0)
#
#     return binary_image
#
#
# def template_density(contour, templates, thresholds, gray_image = raster_image_gray):
#     print('Checking template density...')
#     mask = np.zeros_like(gray_image)
#     cv2.drawContours(mask, [contour], -1, 255, -1)
#     masked_image = cv2.bitwise_and(gray_image, mask)
#
#     total_template_area = 0
#     for i, template in enumerate(templates):
#         res = cv2.matchTemplate(masked_image, template, cv2.TM_CCOEFF_NORMED)
#         loc = np.where(res >= thresholds[i])
#         total_template_area += len(loc[0]) * template.shape[0] * template.shape[1]
#
#     print('... done.')
#     return total_template_area / cv2.contourArea(contour)

# def erase_areas(image, 
#                 factor, 
#                 closed = False, 
#                 black = False, 
#                 circles = False, 
#                 blobs = False, 
#                 contours = True, 
#                 subtract = False,
#                 aspect_ratio_max = .15,
#                 contour_area_min = 2 * MIN_ROAD_WIDTH * MAX_ROAD_WIDTH,
#                 contour_width_max = 3 * MAX_ROAD_WIDTH,
#                 convexity_min = .4,
#                 shading = False,
#                 template_dir = './data/templates',
#                 template_filenames = False,
#                 thresholds = False,
#                 template_density_threshold = .4,
#                 SHOW_IMAGES = False
#                 ):
#     global window, OUTPUTDIR
#     colour = 'black' if black else 'white'
#     shading = 1 if False else -1
#     form = 'shapes' if contours else 'areas'
#     erasure = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
#     image = cv2.bitwise_not(image) if (black and not circles and not blobs) else image
#     size = factor * (MIN_ROAD_WIDTH ** 2) if (contours and not circles and not blobs) else int(factor)
#     if template_filenames:
#         templates = []
#         for i, template_filename in enumerate(template_filenames):
#             templates.append(cv2.imread(f"{template_dir}/{template_filename}", 0))
#
#     if circles: # Used for removing, for example, dot shading (not very effective!)
#         form = 'circles'
#         r = factor
#         size = (2*r+4, 2*r+4)
#         template = np.ones(size, dtype=np.uint8)
#         cv2.circle(template, (r+2,r+2), r, (0,0,0), -1)
#         res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
#         # Threshold the result to find the locations where the image matches the kernel
#         loc = np.where(res >= 0.6)
#         # Draw circles of 8px diameter at the matching locations
#         for pt in zip(*loc[::-1]):
#             cv2.circle(image, (pt[0] + r+2, pt[1] + r+2), r, (255, 255, 255), -1)   
#             cv2.circle(erasure, (pt[0] + r+2, pt[1] + r+2), r, (0, 0, 255, 128), shading)   
#     elif blobs:
#         form = 'blobs'
#         params = cv2.SimpleBlobDetector_Params()
#         params.filterByColor =True
#         params.blobColor = 0 if black == True else 1
#         params.filterByCircularity = True
#         params.maxCircularity = 1
#         params.filterByArea = True
#         params.maxArea = size
#         detector = cv2.SimpleBlobDetector_create(params)
#         keypoints = detector.detect(image)
#         for kp in keypoints:
#             x, y = int(kp.pt[0]), int(kp.pt[1])
#             r = int(kp.size / 2)
#             cv2.circle(image, (x, y), r, (255, 255, 255), -1)
#             cv2.circle(erasure, (x, y), r, (0, 0, 255, 128), shading)                    
#     elif contours:
#         contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
#         if shading:
#             contours = sorted(contours, key=cv2.contourArea, reverse=True)
#         for contour in contours: 
#             # Calculate areas of contour and its convex hull
#             contour_area = cv2.contourArea(contour)
#             hull = cv2.convexHull(contour)
#             hull_area = cv2.contourArea(hull)
#             if hull_area == 0 or contour_area == 0:
#                 cv2.drawContours(erasure, [contour], -1, (0, 255, 255, 128), shading)
#                 continue # Reject contour
#             convexity = contour_area / hull_area
#
#             # Calculate aspect ratio
#             width, height = cv2.minAreaRect(contour)[1]
#             if width == 0 or height == 0:
#                 cv2.drawContours(erasure, [contour], -1, (0, 255, 255, 128), shading)
#                 continue # Reject contour
#             else:
#                 aspect_ratio = min(width, height) / max(width, height)
#
#             if aspect_ratio <= aspect_ratio_max and contour_area >= contour_area_min and min(width, height) <= contour_width_max:
#                 cv2.drawContours(erasure, [contour], -1, (0, 255, 0, 128), shading) # Try not to erase road sections
#             elif convexity >= convexity_min or closed == False: 
#                 cv2.drawContours(image, [contour], 0, (0, 0, 0), -1)
#                 cv2.drawContours(erasure, [contour], -1, (255, 255, 0, 128), shading)
#             else:
#                 # Find template density (can be used, for example, for detecting woodland) - RATHER SLOW
#                 templated = 0
#                 if template_filenames and contour_area >= contour_area_min:
#                     templated = template_density(contour, templates, thresholds)
#                     if templated > template_density_threshold:
#                         print(templated)
#                         cv2.drawContours(image, [contour], 0, (0, 0, 0), -1)
#                         cv2.drawContours(erasure, [contour], -1, (0, 127, 255, 128), shading) # Orange
#                 if templated <= template_density_threshold:
#                     cv2.drawContours(erasure, [contour], -1, (0, 0, 255, 128), shading)
#     else:
#         kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
#         mask = image
#         eroded_image = cv2.erode(image, kernel, iterations=1)
#         dilated_image = cv2.dilate(eroded_image, kernel, iterations=1)
#         image = cv2.subtract(image, dilated_image) if subtract else dilated_image
#         mask = mask != image
#         erasure[mask] = [0, 0, 255, 255]
#     image = cv2.bitwise_not(image) if (black and not circles and not blobs) else image
#     message = 'Removed ' + colour + ' ' + form + ' (size ' + str(size) + ')'
#     print(message)
#
#     if SHOW_IMAGES:
#         cv2.imshow(message + ' [' + str(window) + ']', erasure)
#         cv2.imwrite(os.path.join(OUTPUTDIR, message + ' ' + str(window) + '.png'), erasure)
#         cv2.waitKey(0)
#         window += 1
#
#     return image

############################
## IMAGE PROCESSING CALLS ##
############################

window = 0 # Counter for imshow windows to prevent overwriting
print('Image processing: '+METHOD)
match METHOD:
    
    case 'candidate_areas': # Attempts to filter roads from image in just two calls to the erase_areas function
        result_binary, _ = erase_matches(raster_image_gray, result_binary, './data/templates', 'tree-broadleaf.png', SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR)
        result_binary, _ = erase_matches(raster_image_gray, result_binary, './data/templates', 'tree-conifer.png', threshold=0.7, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR)
        result_binary, _ = erase_areas(result_binary, raster_image_gray, MAX_ROAD_WIDTH ** 2, blobs = True, black = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Attempts to remove circular markers from roadways on GB OS maps
        result_binary, _ = erase_areas(result_binary, raster_image_gray, MIN_ROAD_WIDTH+3, contours = False, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Try to close gaps in road lines
        result_binary, _ = road_contours(raster_image_gray, binary_image = result_binary)
        find_areas(raster_image_gray, SHOW_IMAGES = SHOW_IMAGES)
        # result_binary, _ = erase_matches(raster_image_gray, result_binary, './data/templates', 'road-survey-mark.png', threshold=1, rotation_step = 15, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) #  Finds millions of matches ?!?!?!
        result_binary, _ = erase_areas(result_binary, raster_image_gray,
            factor = 2 * MAX_ROAD_WIDTH / MIN_ROAD_WIDTH, 
            contour_width_max = 3 * MAX_ROAD_WIDTH, 
            convexity_min = .5, 
            closed = True,
            shading = True,
            # template_filenames = ['tree-broadleaf.png','tree-conifer.png'], # Very slow
            thresholds = [.7,.65], 
            SHOW_IMAGES = SHOW_IMAGES, 
            OUTPUTDIR = OUTPUTDIR
            )
    
    case 'progressive':
        # Testing a range of parameters that might be useful for machine learning.
        result_binary, _ = erase_matches(raster_image_gray, result_binary, './data/templates', 'tree-broadleaf.png', SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR)
        result_binary, _ = erase_matches(raster_image_gray, result_binary, './data/templates', 'tree-conifer.png', threshold=0.65, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR)
        result_binary, _ = erase_areas(result_binary, raster_image_gray, MAX_ROAD_WIDTH ** 2, blobs = True, black = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Attempts to remove circular markers from roadways on GB OS maps
        result_binary, _ = erase_areas(result_binary, raster_image_gray, 2, contours = False, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase white noise
        result_binary, _ = erase_areas(result_binary, raster_image_gray, 500, closed = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase white shapes
        # result_binary, _ = erase_areas(result_binary, raster_image_gray, 2, contours = False, black = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase black dots
        # result_binary, _ = erase_areas(result_binary, raster_image_gray, 50, closed = True, black = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase black shapes
        # result_binary, _ = erase_areas(result_binary, raster_image_gray, 120, closed = True, black = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase black shapes
        # result_binary, _ = erase_areas(result_binary, raster_image_gray, 200, black = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase black shapes
        result_binary, _ = erase_areas(result_binary, raster_image_gray, 2 * MAX_ROAD_WIDTH, contours = False, subtract = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase large white areas
        # result_binary, _ = erase_areas(result_binary, raster_image_gray, 500, closed = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase white shapes
        # result_binary, _ = erase_areas(result_binary, raster_image_gray, 1.5 * MAX_ROAD_WIDTH, contours = False, subtract = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase large white areas
        result_binary, _ = erase_areas(result_binary, raster_image_gray, 2/3 * MIN_ROAD_WIDTH, contours = False, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase narrow white areas
        result_binary, _ = erase_areas(result_binary, raster_image_gray, 2000, closed = True, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase white shapes
        result_binary, _ = erase_areas(result_binary, raster_image_gray, 3, contours = False, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR) # Erase white noise
        
    case _: # Default 
        contours, skeleton, base64_images = road_contours(OUTPUTDIR, show_images = True)
        
# Attempt to bridge gaps in skeleton by dilation and re-skeletonization
# def skeleton_contours(skeleton_binary, gap = 15, step = 1, SHOW_IMAGES = False): # Larger steps run risk of blurring
#     print('Skeletonize the binary image and find contours ...')    
#     def skeleton_uint8(img):
#         img = img > 0
#         img = skeletonize(img)
#         return (img * 255).astype(np.uint8)
#     skeleton = skeleton_uint8(skeleton_binary)
#     kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (step,step))
#     for gap_count in range(0, gap, step):
#         skeleton_binary = cv2.dilate(skeleton, kernel, iterations=1)
#         skeleton = skeleton_uint8(skeleton_binary)
#     contours = cv2.findContours(skeleton, cv2.RETR_LIST , cv2.CHAIN_APPROX_NONE)[0]
#     print('... done.')    
#     if SHOW_IMAGES:
#         raster_image_contours = cv2.cvtColor(raster_image_gray, cv2.COLOR_GRAY2BGR)
#         cv2.drawContours(raster_image_contours, contours, -1, (0,0,255), 3)
#         cv2.imshow("Image with Contours", raster_image_contours)
#         cv2.imwrite(os.path.join(OUTPUTDIR, 'Image with contours.png'), raster_image_contours)
#         cv2.waitKey(0)
#     return contours
# contours = skeleton_contours(result_binary, raster_image_gray, SHOW_IMAGES = SHOW_IMAGES, OUTPUTDIR = OUTPUTDIR)

#######################
## VECTOR PROCESSING ##
#######################

print('Convert to LineStrings ...')
## TO DO - split linestrings in proximity of modern road section endpoints, and match them at this stage rather than later
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
