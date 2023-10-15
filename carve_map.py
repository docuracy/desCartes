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

from osgeo import gdal, ogr, osr
from shapely.geometry import mapping, LineString, box
import geopandas as gpd
import os
import math
import numpy as np
import json

def preprocess_map(map_path):
    # Implement preprocessing steps here
    # For example, removing colored pixels, histogram equalization, etc.
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

    empty_geojson = {
        "type": "FeatureCollection",
        "features": []
    }

    map = gdal.Open(map_path)
    map_width, map_height = map.RasterXSize, map.RasterYSize
    horizontal_count, horizontal_overlap, vertical_count, vertical_overlap = calculate_overlaps(map, tile_size, min_overlap)

    print(f"map_width: {map_width}, map_height: {map_height}, horizontal_overlap: {horizontal_overlap}, vertical_overlap: {vertical_overlap}")

    transform = map.GetGeoTransform()  # Get the geotransformation matrix
    x_origin = transform[0]
    y_origin = transform[3]
    pixel_width = transform[1]
    pixel_height = transform[5]

    for x_loop in range(0, horizontal_count):
      for y_loop in range(0, vertical_count):

            x = round(x_loop * (tile_size - horizontal_overlap))
            y = round(y_loop * (tile_size - vertical_overlap))

            print(f"x: {x}-{x+tile_size}, y: {y}-{y+tile_size}")
            tile_name = f"{tile_directory}{region_name}_{x}_{y}.jpg"
            gdal.Translate(tile_name, map, srcWin=[x, y, tile_size, tile_size])

            if annotated is True:
                tile_geojson_path = f"{tile_directory}{region_name}_{x}_{y}.geojson"
                # Calculate the extent in map coordinates
                tile_extent = box(
                    x_origin + x * pixel_width,
                    y_origin + y * pixel_height,
                    x_origin + (x + tile_size) * pixel_width,
                    y_origin + (y + tile_size) * pixel_height
                )
                # Use the extent_geometry to crop 'cropped_labels_gdf' (intersection method does not trim overlapping parts)
                cropped_tile_gdf = gpd.clip(cropped_labels_gdf, tile_extent)
                cropped_tile_gdf = cropped_tile_gdf[~cropped_tile_gdf.is_empty]
                cropped_tile_gdf = cropped_tile_gdf.explode(index_parts=True)  # Cropping can cause creation of multiparts

                if not cropped_tile_gdf.empty:
                    # Transform the coordinates of the cropped_tile_gdf to the image's coordinate system
                    for index, row in cropped_tile_gdf.iterrows():
                        geom = row.geometry
                        geom = transform_coordinates_to_image(geom, transform)
                        cropped_tile_gdf.at[index, 'geometry'] = geom

                    # Save the transformed GeoJSON
                    cropped_tile_gdf.crs = None
                    cropped_tile_gdf.to_file(tile_geojson_path, driver='GeoJSON')

                else:
                    with open(tile_geojson_path, 'w') as json_file:
                        json.dump(empty_geojson, json_file)
