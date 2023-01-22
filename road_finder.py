# -*- coding: utf-8 -*-
"""

@author: Stephen Gadd, Docuracy Ltd, UK

"""

#### Road Finder ####

######################################################################################
"""
NEXT DEVELOPMENT STEPS
Join linestrings within a given distance of each other
Add a quality score to LineString metadata?
Use gdal or shapely to simplify linestrings
Join lines at junctions - no ink on map between nodes
Read array of templates from a directory - might be created directly by clipping map images

"""

import sys, os, subprocess
from osgeo import gdal
from osgeo import ogr
from skimage.metrics import structural_similarity
from skimage.morphology import skeletonize
from sklearn.cluster import KMeans
import skimage.measure
import cv2
import shapefile
import pyproj
import numpy as np
import math
import rasterio
from rasterio.plot import show, reshape_as_raster
from rasterio.crs import CRS
import matplotlib.pyplot as plt
import datetime
import shapely.geometry
from shapely.geometry import Point, MultiPoint, LineString
from shapely.ops import nearest_points, unary_union
import fiona    
import sys
import networkx as nx

ogr2ogr = r'C:\OSGeo4W\bin\ogr2ogr.exe' # Required only if using modern road network shapefile
#####################################################
## User constants, which may be adjusted to improve results

# Template definition
MAX_ROAD_WIDTH = 18  # Should be an even number
MIN_ROAD_WIDTH = 4 # Should be an even number
ROAD_BORDER_THICKNESS = 4
MARGIN = 4 # Typical minimum clear space either side of road
ROAD_COLOUR = (255, 255, 204)
BORDER_COLOUR = (70, 70, 70)
BACKGROUND_COLOUR = (255, 255, 204)

# Processing parameters
NUM_ANGLES = 12 # Number of rotations (within 180 degree bounds) to perform for each template
OUTPUT_RESOLUTION = 1 # Step (in pixels) for scanning raster image both vertically and horizontally
SCORE_CLUSTERS = 7 # Used to find threshold for acceptable template match scores
MAX_CLUSTER = 3 # Used to determine the end of LineStrings, where there are no more acceptable pixel matches
CLOSE_GAP = 3 # Close gaps between LineStrings if their end nodes are within this pixel tolerance

# Map source data - Required only if a new map is required from an XYZ tile-source (requires tiles_to_tiff.py)
EXTENT = [-2.351714,51.501860,-2.327148,51.511414] # Coordinates (lng,lat) of south-west and north-east corners of required map
RASTER_TILE_URL = 'https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=U2vLM8EbXurAd3Gq6C45'
RASTER_TILE_ZOOM = 17 # This has a bearing on the required road-width constants
DATADIR = './data'
GEOTIFF_NAME = 'tormarton.tiff'
MODERN_ROADS = 'oproad_gb_linestrings.gpkg' # Mask map using modern road lines 
MODERN_ROADS = '' # Set to '' to ignore modern road network
MODERN_ROAD_MASK_WIDTH = 80 # Create a buffer either side of road line to allow for the mapped width of roads and account for realignment and inaccurate georeferencing
MODERN_ROAD_EPSG = 27700 

# Input files
GEOTIFF = DATADIR+'/'+GEOTIFF_NAME # If a new map is required, either give a new GEOTIFF_NAME above, or set this constant to ''.
TEMPLATED = '' # Use template-matching results from a previous run. Set to '' to force re-scanning.
TEMPLATED = './output/raw_2023-01-01_10-03-28.npy' # Use template-matching results from a previous run. Set to '' to force re-scanning.
GRAPH = '' # Use graph results from a previous run. Set to '' to force re-calculation.
GRAPH = './output/graph_2023-01-01_19-18-03.gml' # Use graph results from a previous run. Set to '' to force re-calculation.
PATHS = '' # Use paths from a previous run. Set to '' to force re-calculation.
PATHS = './output/paths_2023-01-01_21-47-59.npy' # Use graph results from a previous run. Set to '' to force re-calculation.

# Switches used for development testing
DETECT = False
SHOW_MASK = False
SHOW_TEMPLATES = False
RECLUSTER = False

#####################################################

# Initialise some other variables
w = (ROAD_BORDER_THICKNESS+MARGIN)*2+MAX_ROAD_WIDTH # Maximum template size
masks = [] # Used to clip rotated templates
road_widths = []  # Store the widths of the road templates      
angular_step = 180  // NUM_ANGLES 

# Get the current date and time for use in output filenames
now = datetime.datetime.now()
timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
timestamp = "_{}.".format(timestamp)

if not os.path.exists(GEOTIFF):
    from tiles_to_tiff import create_geotiff        
    create_geotiff (RASTER_TILE_URL, DATADIR, GEOTIFF_NAME, EXTENT, RASTER_TILE_ZOOM)
    GEOTIFF = DATADIR+'/'+GEOTIFF_NAME

# Load the raster image
with rasterio.open(GEOTIFF) as raster:
    raster_image = raster.read()
# Save information about coordinate reference system (CRS)
metadata = raster.meta
# Create copies in different formats
raster_alpha = cv2.merge([raster_image[3,:,:]])
raster_image_colour = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_RGB2BGR)
raster_image_gray = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_BGR2GRAY)

## TO DO: detect and set threshold programmatically
_, result_binary = cv2.threshold(raster_image_gray, 200, 255, cv2.THRESH_BINARY)

# Try to remove shading, which is typically 2px black dots, 2px apart 
kernel = np.ones((3, 3), dtype=result_binary.dtype)
result_binary = cv2.dilate(result_binary, kernel)
result_binary = cv2.erode(result_binary, kernel)
    
# Detect pixels that are not part of centrelines and remove from original alpha channel
result_binary = result_binary > 0
skeleton = skeletonize(result_binary)
skeleton_binary = skeleton.astype(np.uint8)
raster_alpha = np.where(skeleton_binary, raster_alpha, 0)

# Similarly, ignore large areas of the map which have nothing but background colour
## TO DO: set threshold using BACKGROUND_COLOUR constant
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w, w))
closed = cv2.morphologyEx(cv2.bitwise_not(raster_image_gray), cv2.MORPH_CLOSE, kernel)
ret, ignore_mask = cv2.threshold(closed, 127, 255, cv2.THRESH_BINARY)
raster_alpha = np.where(ignore_mask, raster_alpha, 0)

# Also ignore areas outside buffer of modern roads (if set)
if (not MODERN_ROADS == '') and os.path.exists(DATADIR + '/' + MODERN_ROADS):
    output_shapefile = MODERN_ROADS.replace('.gpkg','')+timestamp+'shp'
    bounds = raster.bounds
    if not MODERN_ROAD_EPSG == metadata['crs']:
        bounds = rasterio.warp._warp.transform_bounds(raster.crs, 'EPSG:'+MODERN_ROAD_EPSG, *bounds)
    ogr2ogr = r'C:\OSGeo4W\bin\ogr2ogr.exe'
    ogrcmd = """ogr2ogr -f "ESRI Shapefile" -nlt LINESTRING -explodecollections -spat %s %s %s %s -nln "%s" "%s" "%s" """%(bounds[0], bounds[1], bounds[2], bounds[3], output_shapefile.replace('.shp',''), './output/'+output_shapefile, DATADIR + '/' + MODERN_ROADS)
    response=subprocess.check_output(ogrcmd, shell=True)
    sf = shapefile.Reader('./output/'+output_shapefile)
    # Initialize an empty mask
    modern_road_mask = np.zeros((raster_image_colour.shape[0], raster_image_colour.shape[1]), dtype=np.uint8)
    # Iterate through the LineStrings and MultiLineStrings in the shapefile
    for shape in sf.shapes():
        # Convert the shape to a numpy array of points
        points = np.array(shape.points, dtype=np.int32)
        points = np.stack([rasterio.transform.rowcol(raster.transform, x, y) for x, y in points], axis=0)
        points = points[:, ::-1] # Swap x and y coordinates
        
        # Reject points from lines where they extend beyond the bounds of the geotiff
        boolean_mask = (points[:, 0] >= 0) & (points[:, 0] < modern_road_mask.shape[1]) & (points[:, 1] >= 0) & (points[:, 1] < modern_road_mask.shape[0])
        filtered_points = points[boolean_mask]
        
        # Draw the LineString or MultiLineString on the mask
        cv2.polylines(modern_road_mask, [filtered_points.astype(np.int32)], isClosed=False, color=255, thickness=max(w,MODERN_ROAD_MASK_WIDTH))
    raster_alpha = np.where(modern_road_mask, raster_alpha, 0)

def save_geotiff(result_image, filename, add_alpha=False, show_mask=False):
    # Save the result image as geotiff
    result_tiff = cv2.cvtColor(result_image, cv2.COLOR_BGR2BGRA)  # Convert the image to 4 channels (BGR + alpha)
    result_tiff[:, :, 3] = raster_alpha  # Set the alpha channel to the raster_alpha array

    if not add_alpha == False:
        mask = result_image[:,:,add_alpha] == 0 # Create transparency mask for pixels where V = 0 (when add_alpha == 2)
        result_tiff[mask, 3] = 0 # Add mask to alpha band
        
    if show_mask: # Set to black wherever tranparency is zero
        result_tiff[result_tiff[:,:,3] == 0, :3] = 0
        result_tiff[:, :, 3] = 255
        
    result_tiff = reshape_as_raster(result_tiff)
    with rasterio.open('./output/'+filename+timestamp+'tiff', 'w', **raster.meta) as result:
        result.write(result_tiff)
        return result

save_geotiff(raster_image_colour, 'masked_image', 2, True)

def save_shapefile(lines, filename, hough=False):
    linestrings = []
    for line in lines:
        if hough:
            # Extract the start and end points of the line
            y1, x1, y2, x2 = line[0]
            # Reproject the start and end points using the raster's transform
            x1, y1 = rasterio.transform.xy(raster.transform, x1, y1)
            x2, y2 = rasterio.transform.xy(raster.transform, x2, y2)
            # Create a LineString object using the reprojected start and end points
            line_geom = shapely.geometry.LineString([(x1, y1), (x2, y2)])
            # Append the LineString object to the linestrings list
            linestrings.append(line_geom)
        else:
            linestring = shapely.geometry.LineString(line)
            transformed_coords = []
            for coord in linestring.coords:
                # Use rasterio.transform to transform the coordinate
                x, y = rasterio.transform.xy(raster.transform, coord[0], coord[1])
                transformed_coords.append((x, y))
            linestrings.append( shapely.geometry.LineString(transformed_coords) )
    
    # Set the output shapefile schema
    schema = {
        'geometry': 'LineString',
        'properties': {}
    }
    
    # Open the output shapefile for writing
    with fiona.open('./output/'+filename+timestamp+'shp', 'w', crs=metadata['crs'].to_string(), driver='ESRI Shapefile', schema=schema) as dst:
        # Iterate through the linestrings and write them to the shapefile
        for linestring in linestrings:
            record = {
                'geometry': shapely.geometry.mapping(linestring),
                'properties': {}
            }
            dst.write(record)        

if os.path.exists(TEMPLATED): # Use pre-generated data
    result_image = np.load(TEMPLATED)
    result_image = cv2.cvtColor(result_image, cv2.COLOR_HSV2BGR)
    result_image = cv2.cvtColor(result_image, cv2.COLOR_BGR2HSV)
    save_geotiff(result_image, 'masked_result_geotiff', 2)
    
else:
    for road_width in range(MAX_ROAD_WIDTH, MIN_ROAD_WIDTH-2, -2):
        
        road_widths.append(road_width)
        
        mask_w = (ROAD_BORDER_THICKNESS+MARGIN)*2+road_width
        mask = np.zeros((mask_w, mask_w), dtype=np.uint8)
        cv2.circle(mask, (mask_w //2, mask_w // 2), mask_w // 2, (255, 255, 255), -1)
        masks.append(mask)
    
    # Create a list of template images rotated by different angles
    template_images = [[] for i in range(len(masks))]
    template_angles = [[] for i in range(len(masks))]  # Store the angles of the rotated templates
        
    for i, mask in enumerate(masks):
    
        # Create a blank template image with the specified background color
        template_image = np.full((mask.shape[0], mask.shape[0], 3), BACKGROUND_COLOUR, dtype=np.uint8)
        template_image = cv2.cvtColor(template_image, cv2.COLOR_BGR2GRAY) 
        
        # Draw the line and borders on the template image
        template_image = cv2.rectangle(template_image, (0, mask.shape[0] // 2-ROAD_BORDER_THICKNESS-road_widths[i] // 2), (mask.shape[0], mask.shape[0] // 2+ROAD_BORDER_THICKNESS+road_widths[i] // 2), BORDER_COLOUR, -1)  # borders
        template_image = cv2.rectangle(template_image, (0, mask.shape[0] // 2-road_widths[i] // 2), (mask.shape[0], mask.shape[0] // 2+road_widths[i] // 2), ROAD_COLOUR, -1)  # Line
        
        # Mask the template
        template_image = cv2.bitwise_and(template_image, template_image, mask = mask)
        
        def rotate_image(image, angle):
            rows, cols = image.shape[:2]
            rot_matrix = cv2.getRotationMatrix2D((cols / 2, rows / 2), angle, 1)
            rotated_image = cv2.warpAffine(image, rot_matrix, (cols, rows))
            return rotated_image
        
        for angle in range(0, 179, angular_step):
            rotated_template = rotate_image(template_image, angle)
            template_images[i].append(rotated_template)
            template_angles[i].append(angle)
    
            if SHOW_TEMPLATES:
                cv2.imshow('Template Image', rotated_template)
                cv2.waitKey(0)
                cv2.destroyAllWindows()
    
    # Initialise result image using HSV colour space
    result_image = np.zeros((raster_alpha.shape[0], raster_alpha.shape[1], 3), dtype=np.uint8)
    result_image = cv2.cvtColor(result_image, cv2.COLOR_BGR2HSV)

    if SHOW_MASK:
        # cv2.namedWindow('raster_alpha', cv2.WINDOW_NORMAL)
        # cv2.resizeWindow('raster_alpha', 800, 600)
        cv2.imshow('raster_alpha', raster_alpha)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        
    if DETECT:
        # Iterate over each non-transparent pixel in the raster image
        for y in range(w // 2, (raster_image_gray.shape[0] - w // 2), OUTPUT_RESOLUTION):
        # for y in range(w // 2, 200):
            for x in range(w // 2, (raster_image_gray.shape[1] - w // 2), OUTPUT_RESOLUTION):
                print ('{}/{} of {}/{}'.format(y, x, raster_image_gray.shape[0], raster_image_gray.shape[1]))
                
                if raster_alpha[y][x] == 0: # transparent - ignore
                    continue
                
                # Manually set threshold for matching (might best be set to zero, with thresholding achieved later programmatically)
                best_match_score = 0
                
                for k, mask in enumerate(masks):
                    offset = mask.shape[0] // 2
                    test_square = raster_image_gray[y - offset:y + offset, x - offset:x + offset]
                    test_square = cv2.bitwise_and(test_square, test_square, mask = mask)
                    
                    for template, angle in zip(template_images[k], template_angles[k]):
                        match_score = structural_similarity(cv2.bitwise_and(test_square, test_square, mask = mask), template)
                        
                        # If the match score is higher than the previous best match (or the specified threshold), set the pixel value in the result image to the HSV value
                        # corresponding to the match score (V), road width (S) and the template rotation angle (H)
                        if match_score > best_match_score:
                            best_match_score = match_score
                            result_image[y][x] = np.array([[[angle, int((road_widths[k] - MIN_ROAD_WIDTH) * (road_widths[k] / (MAX_ROAD_WIDTH - MIN_ROAD_WIDTH))), match_score*255]]], dtype=np.float32)                     

        # Save result data in raw format
        np.save('./output/raw'+timestamp+'npy', np.array(result_image))
        
    del template_images, template_angles, road_widths, masks
    
    # Save the result image as png
    cv2.imwrite('./output/result'+timestamp+'png', result_image)
    
    # Save the result image again as geotiff
    result = save_geotiff(result_image, 'result', 2)
    
    # Output metadata and show HSV image
    print (result.meta)
    cv2.imshow('Result Image', result_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

#####################################################
## Create a weighted graph using NetworkX where the weight of each edge between two pixels
## is determined by the relative H, S, and V values.

def cluster_graph(G):
    
    def stringizer(obj):
        if isinstance(obj, tuple):
            return str(obj)
        return str(obj)
    
    print('Starting graph weight clustering ...')
    # Extract the weights from the edges of the graph
    weights = [int(G[u][v]['weight']) for u, v in G.edges()]
    weights = np.array(weights)
    n_clusters=5
    kmeans = KMeans(n_clusters)
    kmeans.fit(weights.reshape(-1, 1))
    cluster_labels = kmeans.predict(weights.reshape(-1, 1))
    # Sort the clusters by the mean weight in each cluster
    cluster_mean_weights = [np.mean(weights[cluster_labels == i]) for i in range(n_clusters)]
    sorted_clusters = np.argsort(cluster_mean_weights)
    # Re-label the clusters in ascending order of weight
    cluster_labels = np.array([sorted_clusters[label] for label in cluster_labels])
    # Add the cluster labels as a new attribute to the graph edges
    for i, (u, v) in enumerate(G.edges()):
        G[u][v]['cluster'] = cluster_labels[i]
    
    nx.write_gml(G,'./output/graph'+timestamp+'gml', stringizer=stringizer)
    

if os.path.exists(GRAPH): # Use pre-calculated graph
    if not os.path.exists(PATHS):
        print('Reading graph ...')
        def destringizer(string):
            if string.startswith("(") and string.endswith(")"):
                return tuple(map(int, string[1:-1].split(",")))
            return float(string)
        
        G = nx.read_gml(GRAPH, destringizer=destringizer)
        
        if RECLUSTER:
            cluster_graph(G)
    
else:
    # Create an empty graph
    print('Starting graph creation ...')
    G = nx.Graph()
    
    def calculate_cost(HSV1,HSV2):
        cost = 255 - HSV2[2] # V
        a1 = abs(HSV1[0] - HSV2[0])
        a2 = abs(HSV1[0] + 180 - HSV2[0])
        if (min(a1, a2) < angular_step * 2): # Similar road orientation
            cost = cost * .5
        if (abs(HSV1[1] - HSV2[1]) < 3): # Similar road width
            cost = cost * .5
        return str(int(cost)) 
    
    # Iterate through the rows and columns of the array
    nodes = 0
    edges = 0
    for y in range(w // 2, result_image.shape[0] - w // 2, OUTPUT_RESOLUTION):
        for x in range(w // 2, result_image.shape[1] - w // 2, OUTPUT_RESOLUTION):
            if raster_alpha[y][x] == 0 or result_image[y, x][2] == 0:
                continue
            print ('{}/{} of {}/{}'.format(y, x, raster_image_gray.shape[0], raster_image_gray.shape[1]))
            # Add a node to the graph for the current pixel
            G.add_node('({}, {})'.format(y,x))
            # Iterate through the 8 adjacent pixels
            for yy in range(y-1, y+2):
                for xx in range(x-1, x+2):
                    # Ignore the masked (transparent) pixels, the current pixel, and any pixels outside the array bounds
                    if raster_alpha[yy][xx] == 0 or result_image[yy, xx][2] == 0 or (yy, xx) == (y, x) or yy < 0 or yy >= result_image.shape[0] or xx < 0 or xx >= result_image.shape[1]:
                        continue
                    # Add an edge to the graph between the current pixel and the adjacent pixel, with the calculated cost as the weight
                    G.add_edge('({}, {})'.format(y,x), '({}, {})'.format(yy,xx), weight=calculate_cost(result_image[y, x], result_image[yy, xx]))
                    
    cluster_graph(G)
    
print('... done.')

#####################################################
## Starting with the highest-scoring pixel, trace the least-cost path below a given cost threshold.
## Repeat from the same start point until all directions have been accounted for.
## Continue with the next highest-scoring pixel that has not yet been absorbed in a path.

def path_from_xy(x, y):
    v_tally[y][x] = 0 # Prevent re-use of this pixel as a start point
    current_pos = (y, x)
    path = [current_pos]
    # Keep going until the path reaches a dead end (i.e., there are no more neighbours with a cost less than the threshold)
    while True:
        # Find the neighbors with the least cost that is below the threshold
        next_pos = None
        if G.has_node(current_pos):
            # Find the neighbours of the current position
            neighbors = G.neighbors(current_pos)
            min_cost = float('inf')
            for neighbor in neighbors:
                cost = G[current_pos][neighbor]['weight']
                if cost < min_cost and G[current_pos][neighbor]['cluster'] < MAX_CLUSTER:
                    min_cost = cost
                    next_pos = neighbor
                    G[current_pos][neighbor]['cluster'] = MAX_CLUSTER + 1 # Prevent re-use of this path
        
        # If no suitable neighbours were found, the path has reached a dead end
        if next_pos is None:
            break
        
        # Otherwise, add the next position to the path and update the current position
        print(next_pos)
        path.append(next_pos)
        current_pos = next_pos
    
    if len(path) > 1:
        return path
    else:
        return False

print('Creating linestrings ...')

if os.path.exists(PATHS):
    stacked_paths = np.load(PATHS)
    nested_padded_paths = np.split(stacked_paths, stacked_paths.shape[0])
    padded_paths = [path[0] for path in nested_padded_paths]
    paths = [path[:np.argmax(np.all(path == (0,0), axis=1))] for path in padded_paths if len(path) > 1]
else:
    paths = []
    # Construct paths based on template matching data stored in the graph
    v_tally = result_image[:, :, 2]
    while True:
        max_v_index = np.argmax(v_tally)  # Find the index of the highest untested V value  
        if np.max(v_tally) == 0:
            break
        x = max_v_index % result_image.shape[1]
        y = max_v_index // result_image.shape[1]
        path = path_from_xy(x, y)
        if path == False: 
            print('No path found')     
        else:
            print (x, y, path, v_tally[y][x], np.max(v_tally))
            paths.append(path)
    # Save paths in raw format
    max_length = max([len(path) for path in paths])
    # Pad the shorter paths with extra points
    padded_paths = [np.pad(path, [(0, max_length - len(path)), (0, 0)], 'constant') for path in paths]
    stacked_paths = np.stack(padded_paths)
    np.save('./output/paths'+timestamp+'npy', stacked_paths)

def merge_paths_by_endpoint(paths):
    # Create an empty dictionary to store the paths by their endpoints
    endpoint_dict = {}
    
    # Iterate through the array of paths
    print('Building path dictionary ...')
    paths = [LineString(path) for path in paths if len(path) > 1]
    for path in paths:
        if len(path) == 0:
            continue
        start_point = tuple(path[0])
        end_point = tuple(path[-1])
        if start_point not in endpoint_dict:
            endpoint_dict[start_point] = [path]
        else:
            endpoint_dict[start_point].append(path)
        if end_point not in endpoint_dict:
            endpoint_dict[end_point] = [path]
        else:
            endpoint_dict[end_point].append(path)
    
    # Iterate through the dictionary
    print('Checking points ...')
    for endpoint, path_list in endpoint_dict.items():
        print(endpoint)
        # Step 3a: If the value associated with the key is a list of more than one path, it means that those paths share an endpoint
        if len(path_list) > 1:
            # Step 3b: Use the unary_union() function to merge the paths into a single path
            merged_path = unary_union(path_list)
            
            # Replace the original paths with the merged path in the dictionary
            endpoint_dict[endpoint] = merged_path
    
    # Return the merged paths as a new array
    merged_paths = list(endpoint_dict.values())
    print('... done.')
    return merged_paths

paths = merge_paths_by_endpoint(paths) # Join paths with coincident endpoints
        
# Fill gaps between nearby endpoints
endpoint_list = []
for path in paths:
    if len(path) < 2:
        continue
    endpoint_list.append(Point(path[0]))
    endpoint_list.append(Point(path[-1]))
endpoint_list = MultiPoint(endpoint_list)

# Find the nearest point to the first point in the list
distance, nearest = nearest_points(endpoint_list.geoms[0], endpoint_list)
distance = distance.distance(nearest)
print(len(endpoint_list.geoms), nearest, distance)

# If the distance is within the threshold and not 0 (because the same point cannot be both the first and nearest points)
if distance <= CLOSE_GAP and distance > 0:
    # Append the nearest point to the list of paths and remove it from the list of endpoints
    paths.append([firstpoint, nearest])
    endpoint_list = MultiPoint([point for point in endpoint_list.geoms if point != nearest])

# Repeat until there are fewer than 2 points remaining in the list of endpoints
while len(endpoint_list.geoms) > 1:
    # Find the nearest point to the first point in the list
    distance, nearest = nearest_points(endpoint_list.geoms[0], endpoint_list)
    distance = distance.distance(nearest)
    print(len(endpoint_list.geoms), nearest, distance)
    # If the distance is within the threshold and not 0
    if distance <= CLOSE_GAP and distance > 0:
        # Append the nearest point to the list of paths and remove it from the list of endpoints
        paths.append([firstpoint, nearest])
        endpoint_list = MultiPoint([point for point in endpoint_list.geoms if point != nearest])
    # If the distance is not within the threshold or is 0, move on to the next point in the list of endpoints
    else:
        endpoint_list = MultiPoint(endpoint_list.geoms[1:])

merge_paths_by_endpoint(paths) # Join paths with coincident endpoints
save_shapefile(paths,'graph_roads_'+str(MAX_CLUSTER)+'_')

sys.exit("Finished execution")

#####################################################
# REDUNDANT CODE
#####################################################
## Use KMeans clustering to find threshold for template match value

V_values = result_image[:,:,2].flatten()
kmeans = KMeans(n_clusters=SCORE_CLUSTERS, max_iter=100, n_init='auto')
kmeans.fit(V_values.reshape(-1, 1))
cluster_labels = kmeans.predict(V_values.reshape(-1, 1))
V_values_means = kmeans.cluster_centers_
highest_V_cluster = np.argmax(V_values_means)
min_V_value = np.min(V_values[cluster_labels == highest_V_cluster])
mask = result_image[:,:,2] < min_V_value  # Create a boolean mask based on the threshold
result_image[mask, 0] = 0  # Set the H values to zero where the mask is True
result_image[mask, 1] = 0  # Set the S values to zero where the mask is True
result_image[mask, 2] = 0  # Set the V values to zero where the mask is True

save_geotiff(result_image, 'result_thresholded', 2)

cv2.imshow('result_image_thresholded', result_image) 
cv2.waitKey(0)
cv2.destroyAllWindows()

#####################################################
## Convert to LineStrings

# THIS IS NOT USEFUL - separate contours and unconnected linestrings are generated for each pixel

import skimage.measure

_, result_binary = cv2.threshold(result_image[:,:,2], 1, 255, cv2.THRESH_BINARY)
cv2.imshow('result_image > 0', result_binary.astype(np.uint8)) 
cv2.waitKey(0)
cv2.destroyAllWindows()

contours = skimage.measure.find_contours(result_binary, 1)
linestrings = [shapely.geometry.LineString(contour) for contour in contours]

print(linestrings)
save_shapefile(linestrings,'skeleton_roads')
#####################################################
## Use KMeans clustering to group similar road widths and orientations

# THIS IS NOT USEFUL - each pixel needs to be examined in a more detailed context

# Extract the H values for each pixel in the image
hsv_values = result_image[:,:,:1].reshape(-1,1) 

# Create a KMeans object and fit it to the data
kmeans = KMeans(n_clusters=NUM_ANGLES, max_iter=100, n_init='auto')
kmeans.fit(hsv_values)

# Get the cluster labels for each pixel
cluster_labels = kmeans.predict(hsv_values)

# Visualisation: Reshape the cluster labels back into the same shape as the image
cluster_image = cluster_labels.reshape(result_image.shape[:2])
plt.imshow(cluster_image, cmap='viridis')
plt.show()

#####################################################
## Try Hough line detection on KMeans clusters (not very good at picking up short lines, and many false positives)

cluster_labels = cv2.normalize(cluster_labels, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8UC1)
cluster_image = cluster_labels.reshape(result_image[:,:,:2].shape[:2])

# Detect lines
hough_lines = cv2.HoughLinesP(cluster_image, 1, 2*np.pi/180, 252, 180, 80)
# Make a copy of the original image
image_with_lines = raster_image_colour.copy()

# Iterate through the lines
for line in hough_lines:
    # Extract the start and end points of the line
    x1, y1, x2, y2 = line[0]
    # Draw the line on the image
    cv2.line(image_with_lines, (x1, y1), (x2, y2), (0, 0, 255), 2)

cv2.imshow('image_with_lines', image_with_lines) 
cv2.waitKey(0)
cv2.destroyAllWindows()

print(hough_lines)
save_shapefile(hough_lines,'hough_roads',True)
#####################################################