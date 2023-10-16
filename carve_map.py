#@title Carve Map
'''
carve_map.py

@author: Stephen Gadd, Docuracy Ltd, UK

This script is used for processing and splitting large maps into smaller tiles 
with associated annotations. It can be configured for various map preprocessing 
steps and is designed for use in geographic information system (GIS) workflows,
and to produce training and test data for machine-learning processes.
 
The script leverages libraries such as GDAL, GeoPandas, and Shapely for efficient 
map processing.

Key Functions:

- preprocess_map(map_path):
  Implement any preprocessing steps for the map, such as removing coloured pixels, 
  histogram equalization, etc.

- calculate_overlaps(map, tile_size, min_overlap):
  Calculate the number of tiles, horizontal and vertical overlaps based on map size 
  and desired tile size.

- split_map(map_path, cropped_labels_gdf, tile_directory, tile_size, min_overlap, region_name, annotated):
  Split the map into smaller tiles and associated GeoJSON annotations. The script takes 
  care of the transformation, cropping, and saving of the tiles and annotations.

'''
#!pip install rasterio # Required for Colab

from osgeo import gdal, ogr, osr
from shapely.geometry import mapping, LineString, box, shape
import geopandas as gpd
from affine import Affine
import rasterio.features
import rasterio.enums
import os
import math
import numpy as np
import json

def preprocess_map(map_path):
    # Implement preprocessing steps here
    # For example, removing coloured pixels, histogram equalisation, etc.
    pass
            
def calculate_overlaps(map, tile_size, min_overlap):
    map_width, map_height = map.RasterXSize, map.RasterYSize

    horizontal_count = math.ceil((map_width - min_overlap) / (tile_size - min_overlap))
    vertical_count = math.ceil((map_height - min_overlap) / (tile_size - min_overlap))

    horizontal_overlap = (tile_size * horizontal_count - map_width) / (horizontal_count - 1)
    vertical_overlap = (tile_size * vertical_count - map_height) / (vertical_count - 1)

    return horizontal_count, horizontal_overlap, vertical_count, vertical_overlap

def transform_coordinates_to_image(geometry, transform):
    transformed_coords = []
    for coord in geometry.coords:
        x_image = round((coord[0] - transform[0]) / transform[1])
        y_image = round((coord[1] - transform[3]) / transform[5])
        transformed_coords.append((x_image, y_image))
    return LineString(transformed_coords)    
  
def split_map(map_path, cropped_labels_gdf, tile_directory, tile_size, min_overlap, region_name, annotated):

    map = gdal.Open(map_path)
    map_width, map_height = map.RasterXSize, map.RasterYSize
    horizontal_count, horizontal_overlap, vertical_count, vertical_overlap = calculate_overlaps(map, tile_size, min_overlap)

    print(f"map_width: {map_width}, map_height: {map_height}, horizontal_overlap: {horizontal_overlap}, vertical_overlap: {vertical_overlap}")

    if annotated is True:

        transform = map.GetGeoTransform()  # Get the geotransformation matrix
        
        # Collect shapes
        shapes = []
        for index, row in cropped_labels_gdf.iterrows():
            row['geometry'] = transform_coordinates_to_image(row['geometry'], transform)
            shapes.append((row['geometry'], row['type']))

        # Sort the shapes in descending order of 'type' value (primary roads drawn last)
        shapes.sort(key=lambda x: x[1], reverse=True)

        # Use rasterio.features.rasterize with the sorted shapes list
        label_image = rasterio.features.rasterize(
            shapes=shapes,
            out_shape=(map_height, map_width),
            fill=0,
            all_touched=True,
            merge_alg=rasterio.enums.MergeAlg.replace,
            dtype=np.uint8
        )
        
        num_classes = np.max(label_image) # Allows for fill (zero) and road classes 1 or greater 
        np.save(f"{map_path}.npy", np.eye(num_classes)[label_image]) # One-hot encode the label image

    for x_loop in range(0, horizontal_count):
        for y_loop in range(0, vertical_count):

            x = round(x_loop * (tile_size - horizontal_overlap))
            y = round(y_loop * (tile_size - vertical_overlap))

            # print(f"x: {x}-{x+tile_size-1}, y: {y}-{y+tile_size-1}")
            tile_name = f"{tile_directory}{region_name}_{x}_{y}.jpg"
            gdal.Translate(tile_name, map, srcWin=[x, y, tile_size, tile_size])

            if annotated is True:
                # Create a road image for the current tile
                label_tile = label_image[y:y + tile_size, x:x + tile_size]
                label_tile_path = f"{tile_directory}{region_name}_{x}_{y}.npy"
                np.save(label_tile_path, label_tile)
