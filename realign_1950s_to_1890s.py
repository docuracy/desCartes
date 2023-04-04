'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''

import rasterio
import cv2
import numpy as np
import os
import sys
import json
import uuid
import geopandas as gpd
from shapely.geometry import MultiPoint, Point, LineString, Polygon, box
from shapely.ops import polygonize
from skimage import morphology
from skimage.measure import label, regionprops
from skimage.morphology import skeletonize, medial_axis
from skimage.draw import line
from skimage.graph import route_through_array
from utilities import unit_vector, imshow_size, ends_and_junctions
from desCartes import cut, result_image, XY_to_EPSG4326, zip_files, extract_dashed_paths, draw_linestrings_on_image
from tiles_to_tiff import create_geotiff
from coloured_roads import coloured_roads, endpoint_connectivity
from scipy.spatial.distance import cdist
from scipy.ndimage import distance_transform_edt

def realign_1950s_to_1890s( 
        map_directory = None,
        map_defaults_file = "./webapp/data/map_defaults.json",
        source = {
            "map_defaults_key": 1,
            "filename": "geo-1950s.tiff"
            }, 
        target = {
            "map_defaults_key": 0,
            "filename": "geo-1890s.tiff"
            },
        extent = {
            "sw_lng": None,
            "sw_lat": None,
            "ne_lng": None,
            "ne_lat": None
            },
        max_sample_distance = 10, 
        sample_width = 50, 
        road_width = {"max": 20, "min": 5}, 
        visualise = True, 
        show_images = True):
    
    bounds = [extent["sw_lng"], extent["sw_lat"], extent["ne_lng"], extent["ne_lat"]]
    
    print(f'Starting to realign vectors to raster image ...')
    
    if map_directory == None:
        map_directory = './output/' + str(uuid.uuid4()) + '/'
    
    result_images = []
    
    with open(os.path.join(os.path.dirname(__file__), map_defaults_file), 'r') as file:
        map_defaults = json.load(file)
        
    source_raster_OK = False
    if os.path.exists(map_directory + source["filename"]):   
        with rasterio.open(map_directory + source["filename"]) as source_raster:
            if [round(coord, 3) for coord in bounds] == [round(coord, 3) for coord in source_raster.bounds]:
                print('Source raster bounds OK.')
                source_raster_OK = True
                source_raster_image = source_raster.read()
        # TO DO: Consider reading result_image info from map_directory (lacks labelling)
        
    if source_raster_OK == False:
        if extent["sw_lng"] == None:
            sys.exit(f'If you do not specify an extent, {map_directory + source["filename"]} must already have been created.')
        create_geotiff(map_defaults[source["map_defaults_key"]]["url"], map_directory, source["filename"], bounds, map_defaults[source["map_defaults_key"]]["zoom"])
        print('Source raster created.')
        
        with rasterio.open(map_directory + source["filename"]) as source_raster:
            source_raster_image = source_raster.read()
    
    # Check that target raster exists and has correct extent
    target_raster_OK = False
    if os.path.exists(map_directory + target["filename"]):
        with rasterio.open(map_directory + target["filename"]) as target_raster:
            if [round(coord, 3) for coord in source_raster.bounds] == [round(coord, 3) for coord in target_raster.bounds]:
                print('Target raster bounds OK.')
                target_raster_OK = True
                target_tiff = target_raster.read()
        
    if target_raster_OK == False:   
        create_geotiff(map_defaults[target["map_defaults_key"]]["url"], map_directory, target["filename"], bounds, map_defaults[target["map_defaults_key"]]["zoom"])
        print('Target raster created.')
        with rasterio.open(map_directory + target["filename"]) as target_raster:
            target_tiff = target_raster.read()
        
    # Create greyscale and binary versions of raster image
    target_image = cv2.cvtColor(target_tiff.transpose(1, 2, 0), cv2.COLOR_RGB2BGR) # Convert from TIFF to BGR
    target_image_grey = cv2.cvtColor(target_image, cv2.COLOR_BGR2GRAY)
    target_image_grey = cv2.medianBlur(target_image_grey, int(map_defaults[target["map_defaults_key"]]["blur_size"]))
    _, target_image_otsu = cv2.threshold(target_image_grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU) # Tends to create gaps in road lines
    _, target_image_binary = cv2.threshold(target_image_grey, map_defaults[target["map_defaults_key"]]["binarization_threshold"], 255, cv2.THRESH_BINARY)
    
    imshow_size('target_image', target_image)
            
    # Check 1950s road vectors in desCartes.gpkg, and call coloured_roads if necessary
    geopackage_OK = False
    if os.path.exists(map_directory + 'desCartes.gpkg'):
        EPSG4326_gdf = gpd.read_file(map_directory + 'desCartes.gpkg', layer='coloured_roads')
        if not EPSG4326_gdf.empty:
            print('Source vector file OK.')
            geopackage_OK = True
            # Transform gdf to target XY-CRS
            coords_list = list(EPSG4326_gdf.geometry.apply(lambda geom: list(geom.coords)).values)
            roads = gpd.GeoDataFrame(geometry=gpd.GeoSeries([LineString([(coord[1], coord[0]) for coord in [rasterio.transform.rowcol(target_raster.transform, coord[0], coord[1]) for coord in coords]]) for coords in coords_list]))
            roads = roads.join(EPSG4326_gdf.drop('geometry', axis=1))    
            
    if geopackage_OK == False: 
        print('Generating source vector file.')
        colours = json.dumps(map_defaults[source["map_defaults_key"]]["colours"])
        roads, _, source_result_images, _ = coloured_roads(source_raster_image, map_directory, source_raster.transform, colours = colours, visualise = visualise, show_images = False)
        result_images.extend(source_result_images)
    
    # Get footpath vectors and delete dashes from target raster
    print('Extracting footpath vectors.')
    footpaths, footpaths_double, footpaths_single = extract_dashed_paths(target_image_otsu, map_defaults[target["map_defaults_key"]]["dash_detector"])
    
    target_image_binary = np.where(footpaths == 255, 255, target_image_binary) # Remove dashes
    
    # # compute the distance transform of the binarized raster
    # print('Computing distance transforms ...')
    #
    # assign scores based on the distance to the skeleton, the maximum gap size, and the maximum road width
    min_road_width = map_defaults[target["map_defaults_key"]]["MIN_ROAD_WIDTH"]
    gap_close = map_defaults[target["map_defaults_key"]]["gap_close"]
    max_road_width = map_defaults[target["map_defaults_key"]]["MAX_ROAD_WIDTH"]
    max_half_gap = max(gap_close, max_road_width) / 2
    #
    # dt_white = distance_transform_edt(target_image_otsu == 255)
    # dt_white_expanse = distance_transform_edt(dt_white < max_half_gap)
    # dt_black = distance_transform_edt(target_image_otsu == 0)
    #
    # scores = np.zeros_like(dt_white, dtype=np.uint8)
    #
    # scores[(min_road_width / 2 <= dt_white) & (dt_white <= max_half_gap)] = 1 + max_half_gap - dt_white[(min_road_width / 2 <= dt_white) & (dt_white <= max_half_gap)]
    # scores[(min_road_width / 2 > dt_white) & (target_image_otsu == 255)] = max_half_gap
    # scores[(dt_black <= 5) & (target_image_otsu == 0)] = 1 + max_half_gap + 2 * dt_black[(dt_black <= 5) & (target_image_otsu == 0)]
    #
    # scores_max = scores.max()
    #
    # scores[(dt_white > 1 + max_half_gap) & (target_image_otsu == 255)] = scores_max
    # scores[(dt_white_expanse <= max_half_gap + 1) & (dt_white <= max_half_gap + 1)] = scores_max
    # scores[(dt_black > 5) & (target_image_otsu == 0)] = scores_max
    #
    # # normalize range 0 to 1
    # scores = (scores - scores.min()) / (scores.max() - scores.min())
    #
    # visualisation_scores = cv2.resize(scores, target_image.shape[:2][::-1])
    # visualisation = target_image.copy()
    # visualisation[visualisation_scores > 0, 2] = visualisation_scores[visualisation_scores > 0] * 255
    # visualisation[visualisation_scores > 0, 1] = 255 * (1 - visualisation_scores[visualisation_scores > 0])
    # visualisation[visualisation_scores > 0, 0] = 127
    # imshow_size('visualisation', visualisation, wait = True)
    
    # Select only top-level contours (in effect, areas which can trace a white route to the edge of the image)
    print('Finding white areas contiguous to edges.')
    # contours, hierarchy = cv2.findContours(cv2.bitwise_not(target_image_otsu), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours, hierarchy = cv2.findContours(cv2.bitwise_not(target_image_binary), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    top_contours_indices = [i for i, h in enumerate(hierarchy[0]) if h[3] == -1 and cv2.contourArea(contours[i]) > 500]
    top_contours = [contours[i] for i in top_contours_indices]
    target_image_processed = np.ones_like(target_image_otsu, dtype=np.uint8) * 255  # create white image
    cv2.drawContours(target_image_processed, top_contours, -1, 0, -1)
    
    imshow_size('target_image_processed', target_image_processed)
    
    # # Limit detection to area within a buffer distance of 1950s roads
    # mask = np.zeros_like(target_image_otsu, dtype=np.uint8) * 255  # create black image
    # draw_linestrings_on_image(mask, roads, 255, 300)
    # target_image_processed = cv2.bitwise_and(target_image_processed, mask)
    
    ## Skeletonize
    print("Skeletonizing ...")
    skeleton = skeletonize(target_image_processed / 255.).astype(np.uint8) * 255
    
    imshow_size('skeleton', skeleton)
    
    
    # Now remove skeleton objects which include pixels further than max_half_gap from a black pixel in the processed target image
    scored_target = distance_transform_edt(target_image_processed == 255)
    scored_target = cv2.resize(scored_target, target_image.shape[:2][::-1])
    
    labels = label(skeleton)
    
    scored_skeleton = skeleton.copy()
    scored_skeleton[scored_skeleton == 255] = scored_target[scored_skeleton == 255] 
    
    unique_labels = np.unique(labels[scored_skeleton > max_half_gap])
    mask = np.in1d(labels, unique_labels).reshape(labels.shape)
    skeleton[mask] = 0
    skeleton[scored_target < min_road_width/2] = 0
    
    imshow_size('trimmed_skeleton', skeleton) 
    
    # Find endpoints of skeleton
    endpoints, junctions = ends_and_junctions(skeleton)
    # Visualize the endpoints and junctions
    endpoints_img = np.zeros_like(skeleton)
    for i, j in endpoints:
        endpoints_img[i, j] = 255
    cv2.imshow('Endpoints', endpoints_img)
    
    junctions_img = np.zeros_like(skeleton)
    for i, j in junctions:
        junctions_img[i, j] = 255
    cv2.imshow('Junctions', junctions_img)
    
    ## IN ADDITION TO THE FOLLOWING link endpoints to closest points on differently labelled segments
    
    
    # loop over pairs of endpoints
    for i in range(len(endpoints)-2):
        for j in range(i+1, len(endpoints)):
            # calculate distance between endpoints
            dist = np.linalg.norm(endpoints[i] - endpoints[j])
            
            # if distance is less than gap_close, draw a line between endpoints
            if dist < gap_close:
                cv2.line(skeleton, tuple(endpoints[i][::-1]), tuple(endpoints[j][::-1]), 255, thickness=1)
    
    imshow_size('joined_skeleton', skeleton)

    kernel_size = int(max_half_gap)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    skeleton = cv2.dilate(skeleton.astype(np.uint8), kernel)
    skeleton = skeletonize(skeleton / 255.).astype(np.uint8) * 255
    
    imshow_size('re-skeletonized_skeleton', skeleton)
    
    target_with_skeleton = target_image.copy()
    target_with_skeleton[skeleton == 255, 2] = 255
    cv2.imshow('target_with_skeleton', target_with_skeleton)
    

    print('Visualising. Press any key to continue:')
    cv2.waitKey(0)
                        
         
    
    
    
    
    
    # compute the distance transform of the skeleton
    dt = np.zeros_like(skeleton, dtype=np.float64)
    dt[skeleton] = 255
    dt = distance_transform_edt(dt)

    # assign scores based on the distance to the skeleton and the gap size
    scores = np.full_like(skeleton, fill_value=np.inf, dtype=np.float64)
    scores[np.logical_and(dt <= map_defaults[target["map_defaults_key"]]["gap_close"]/2, dt > 0)] = 3
    scores[skeleton == 255] = 1
    
    # Identify nodes where skeleton meets edge of image
    height, width = skeleton.shape
    edge_nodes = [(x, 0) for x in range(width) if skeleton[0, x] == 255] + \
        [(x, height-1) for x in range(width) if skeleton[height-1, x] == 255] + \
        [(0, y) for y in range(1, height-1) if skeleton[y, 0] == 255] + \
        [(width-1, y) for y in range(1, height-1) if skeleton[y, width-1] == 255]

    # Create a binary image of the same size as 'scores'
    paths_image = np.zeros_like(scores, dtype=np.uint8)

    # Iterate over all pairs of edge nodes
    for i, start_node in enumerate(edge_nodes):
        for j, end_node in enumerate(edge_nodes):
            # Skip if start and end nodes are the same
            if j <= i:
                continue
            # Find the shortest path between the start and end nodes
            try:
                indices, _ = route_through_array(scores, start_node, end_node)
                # indices = np.array(indices)
                # get the start and end coordinates of the line
                start_row, start_col = indices[0]
                end_row, end_col = indices[-1]
                
                # draw the line on the output image
                rr, cc = line(start_row, start_col, end_row, end_col)
                paths_image[rr, cc] = 255             
            except ValueError:
                print(f"No minimum-cost path was found between {start_node} and {end_node}")
            
    imshow_size('paths_image', paths_image)                                                     
    
    print('Visualising. Press any key to continue:')
    cv2.waitKey(0)
    
    ## Find several least cost paths through skeleton for each pair of road endpoints and pick closest in length
    
    # find the shortest path between two points
    start = (0, 0)
    end = (4, 4)
    indices, costs = route_through_array(scores, start=start, end=end)
    
    # compute distance transform of indices in order to smooth path
    
    
    
    
    
    if show_images:
        visualisation = target_image.copy()
        # visualisation[np.where((footpaths == 255))] = [0, 255, 255] # Colour detected dashes
        # for gdf, colour in zip([roads, footpaths_double, footpaths_single],[(0, 0, 255), (0, 255, 0), (255, 0, 0)]):
        #     draw_linestrings_on_image(visualisation, gdf, colour, 2)
        visualisation = cv2.resize(visualisation, (0, 0), fx=0.4, fy=0.4)
        cv2.imshow('visualisation', visualisation)
        target_image_processed = cv2.resize(target_image_processed, (0, 0), fx=0.4, fy=0.4)
        cv2.imshow('target_image_processed', target_image_processed)
        skeleton = cv2.resize(skeleton, (0, 0), fx=0.4, fy=0.4)
        cv2.imshow('skeleton', skeleton)
        print('Visualising. Press any key to continue:')
        cv2.waitKey(0)
        print('... continuing ...')
    
    # Iterate over gdf geometries, searching for parallel road profile in target raster (or footpath vector)
    
    # Add sequences of matched points to new gdf together with source line ID; omit unmatched sections
    
    # Create dictionary of endpoint junctions, then project endpoints and find median of intersections to relocate junctions and extend connected lines
    endpoints, connected_endpoints, unconnected_endpoints, endpoint_dictionary = endpoint_connectivity(roads, shape = False, margin = 0, full_dictionary = True)
    
    print(f'... completed realignment of vectors to raster image.')
    return