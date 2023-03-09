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
from shapely.geometry import MultiPoint, Point, LineString
from utilities import unit_vector
from desCartes import cut, result_image, XY_to_EPSG4326, zip_files, extract_dashed_paths
from tiles_to_tiff import create_geotiff
from coloured_roads import coloured_roads, endpoint_connectivity

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
    
    with open(map_defaults_file, 'r') as file:
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
    _, target_image_otsu = cv2.threshold(target_image_grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU) # Tends to create gaps in road lines
    _, target_image_binary = cv2.threshold(target_image_grey, map_defaults[target["map_defaults_key"]]["binarization_threshold"], 255, cv2.THRESH_BINARY)
            
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
    
    if show_images:
        visualisation = target_image.copy()
        visualisation[np.where((footpaths == 255))] = [0, 255, 255] # Colour detected dashes
        for gdf, colour in zip([roads, footpaths_double, footpaths_single],[(0, 0, 255), (0, 255, 0), (255, 0, 0)]):
            for _, lineString in gdf.iterrows():
                coords = np.array(lineString.geometry.coords)
                coords = coords.astype(np.int32).reshape(-1, 1, 2)
                cv2.polylines(visualisation, [coords], isClosed=False, color=colour, thickness=2)
        visualisation = cv2.resize(visualisation, (0, 0), fx=0.4, fy=0.4)
        cv2.imshow('visualisation', visualisation)
        print('Visualising. Press any key to continue:')
        cv2.waitKey(0)
        print('... continuing ...')
    
    # Iterate over gdf geometries, searching for parallel road profile in target raster (or footpath vector)
    
    # Add sequences of matched points to new gdf together with source line ID; omit unmatched sections
    
    # Create dictionary of endpoint junctions, then project endpoints and find median of intersections to relocate junctions and extend connected lines
    endpoints, connected_endpoints, unconnected_endpoints, endpoint_dictionary = endpoint_connectivity(roads, shape = False, margin = 0, full_dictionary = True)
    
    print(f'... completed realignment of vectors to raster image.')
    return
    
# TEST function
realign_1950s_to_1890s(map_directory = "./output/576a2b38-44e1-40ce-bccb-007b2919fea9/", extent = {
            "sw_lng": -1.065233614878051,
            "sw_lat": 51.81467381756681, 
            "ne_lng": -1.0354690510152538,
            "ne_lat": 51.83314025759576
            })