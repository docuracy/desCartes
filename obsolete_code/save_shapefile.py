"""
@author: Stephen Gadd, Docuracy Ltd, UK

This code takes a list of linestrings linestrings, a rasterio transformation, 
and a shapefile filename filename as input. It iterates through the linestrings, 
converts them to Shapely LineString objects, transforms the coordinates using the 
rasterio.transform.xy function, converts the transformed coordinates back 
to Shapely LineString objects, and stores them in a list.

It then sets the output shapefile schema and opens the shapefile for writing. 
It iterates through the transformed linestrings, creates a record for each one, 
and writes the record to the shapefile.

"""
import shapely.geometry
import rasterio
import fiona

def save_shapefile(linestrings, transformation, metadata, filename, attributes = False, modern_linklines = False):
    if not modern_linklines == False:
        # Set the output shapefile schema
        schema = {
            'geometry': 'LineString',
            'properties': {
            }
        }
        # Open the output shapefile for writing
        with fiona.open(filename.replace('.shp','_links.shp'), 'w', crs='EPSG:4326', driver='ESRI Shapefile', schema=schema) as dst:
            # Iterate through the linestrings_transformed and write them to the shapefile
            for linestring in modern_linklines:
                # Create a record for the linestring
                record = {
                    'geometry': shapely.geometry.mapping(linestring),
                    'properties': {}
                }
                # Write the record to the shapefile
                dst.write(record)
    
    # Initialize an empty list to store the transformed linestrings
    linestrings_transformed = []
    # Iterate through the linestrings
    for linestring in linestrings:
        # Convert the linestring to a Shapely LineString object
        linestring = shapely.geometry.LineString(linestring)
        # Initialize an empty list to store the transformed coordinates
        transformed_coords = []
        # Iterate through the coordinates of the linestring
        for coord in linestring.coords:
            # Use rasterio.transform to transform the coordinate
            longitude, latitude = rasterio.transform.xy(transformation, coord[1], coord[0])
            # Add the transformed coordinate to the list
            transformed_coords.append((longitude, latitude))
        # Convert the transformed coordinates to a Shapely LineString object and add it to the list
        linestrings_transformed.append( shapely.geometry.LineString(transformed_coords) )

    # Set the output shapefile schema
    schema = {
        'geometry': 'LineString',
        'properties': {
            'score': 'float',
            'width': 'float',
            # 'modernity': 'float'
            'modernity': 'str'
        }
    }

    # Open the output shapefile for writing
    with fiona.open(filename, 'w', crs=metadata['crs'].to_string(), driver='ESRI Shapefile', schema=schema) as dst:
        # Iterate through the linestrings_transformed and write them to the shapefile
        for linestring, attr in zip(linestrings_transformed, attributes):
            # Create a record for the linestring
            record = {
                'geometry': shapely.geometry.mapping(linestring),
                'properties': attr
            }
            # Write the record to the shapefile
            dst.write(record)
    
    return linestrings_transformed