import math
import rasterio
import numpy as np
import cv2
from skimage.metrics import structural_similarity
from shapely.geometry import Point, LineString, MultiLineString
from shapely import ops
import geopandas as gpd
            
from shapely.ops import nearest_points
from shapely.ops import unary_union
from collections import Counter
from rtree import index

def generate_templates(MAX_ROAD_WIDTH, MIN_ROAD_WIDTH):
    # Template definitions
    ROAD_BORDER_THICKNESS = 4 # Pixel width of lines defining road edges
    MARGIN = 4 # Typical minimum clear space either side of road
    ROAD_COLOUR = (255, 255, 204)
    BORDER_COLOUR = (70, 70, 70)
    BACKGROUND_COLOUR = (255, 255, 204)
    
    template_images = []
    for road_width in range(MAX_ROAD_WIDTH, MIN_ROAD_WIDTH-2, -2):
        template_w = (ROAD_BORDER_THICKNESS+MARGIN)*2+road_width
        # Create a blank template image with the specified background color
        template_image = np.full((template_w, template_w, 3), BACKGROUND_COLOUR, dtype=np.uint8)
        template_image = cv2.cvtColor(template_image, cv2.COLOR_BGR2GRAY) 
        
        # Draw the line and borders on the template image
        template_image = cv2.rectangle(template_image, (0, template_w // 2-ROAD_BORDER_THICKNESS-road_width // 2), (template_w, template_w // 2+ROAD_BORDER_THICKNESS+road_width // 2), BORDER_COLOUR, -1)  # borders
        template_image = cv2.rectangle(template_image, (0, template_w // 2-road_width // 2), (template_w, template_w // 2+road_width // 2), ROAD_COLOUR, -1)  # Line
        
        # Mask the template
        template_images.append(template_image)
    
    return template_images

def score_linestrings(linestrings, TEMPLATE_SAMPLE, raster_image_gray, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, modern_roads, transform, MAX_MODERN_OFFSET):
    # Test sample points from extracted LineStrings for structural_similarity to roads, 
    # using templates rotated to the orientation of the LineString at each sample point.
    # Filter out all LineStrings not meeting minimum similarity threshold. 
    
    templates = generate_templates(MAX_ROAD_WIDTH, MIN_ROAD_WIDTH)
    linestring_attributes = []
    modern_linklines = []
    
    def angle_between_points(p1, p2, p3):
        angle1 = math.atan2(p2.y - p1.y, p2.x - p1.x)
        angle2 = math.atan2(p3.y - p2.y, p3.x - p2.x)
        angle = angle2 - angle1
        return math.degrees(angle)
    
    # Create an R-tree spatial index for the modern road vectors
    idx = index.Index()
    for i, line in modern_roads.iterrows():
        idx.insert(i, line.geometry.bounds)
    
    for k, (linestring) in enumerate(linestrings):
        print("{}/{}".format(k, len(linestrings)))
        if (linestring.length < TEMPLATE_SAMPLE):
            linestring_attributes.append({'score': 0, 'width': 0, 'modernity': ''})
            continue
        scores = []
        widths = []
        modern = []
        
        for i in range(0, int(linestring.length)-TEMPLATE_SAMPLE, TEMPLATE_SAMPLE):
            point1 = linestring.interpolate(i)  # get the Point at distance i along the LineString
            point2 = linestring.interpolate(i+TEMPLATE_SAMPLE)  # get the Point at distance i+TEMPLATE_SAMPLE along the LineString
            orientation = math.degrees(math.atan2(point2.y - point1.y, point2.x - point1.x))
            
            clip_size = int(templates[0].shape[0] * math.sqrt(2)) # Maximum dimension of rotated templates
            clip_region = cv2.getRectSubPix(raster_image_gray, (clip_size, clip_size), (point1.x, point1.y), cv2.INTER_CUBIC)
            rot_matrix = cv2.getRotationMatrix2D((clip_size / 2, clip_size / 2), orientation, 1)
            clip_region = cv2.warpAffine(clip_region, rot_matrix, (clip_size, clip_size), cv2.INTER_CUBIC)
            clip_region = cv2.getRectSubPix(clip_region, (templates[0].shape[0],templates[0].shape[0]), (clip_size / 2, clip_size / 2))
            
            for j, (template) in enumerate(templates):
                clip_sample = cv2.getRectSubPix(clip_region, (template.shape[0],template.shape[0]), (clip_region.shape[0] / 2, clip_region.shape[0] / 2))
                
                match_score = structural_similarity(template, clip_sample)
                if np.isnan(match_score):
                    match_score = -1
                if j == 0:
                    scores.append(match_score)
                    widths.append(template.shape[0])
                else:
                    # Score the best match from different templates at this point
                    if match_score > scores[-1]:
                        scores[len(scores)-1] = match_score
                        widths[len(scores)-1] = template.shape[0]
                        
            
            # Now check for proximity to a modern road with similar orientation
            test_point = Point(rasterio.transform.xy(transform, point1.y, point1.x))
            test_point2 = Point(rasterio.transform.xy(transform, point2.y, point2.x))
            closest_line = modern_roads.iloc[next(idx.nearest(test_point.coords[0], 1))]
            closest_distance = test_point.distance(closest_line.geometry)
            closest_point = closest_line.geometry.interpolate(closest_line.geometry.project(test_point))
            bearing_difference = abs((angle_between_points(test_point2, test_point, closest_point) % 180) - 90)
            modern.append([point1,closest_line.id,closest_distance,bearing_difference])
            modern_linklines.append(LineString([test_point.coords[0], closest_point.coords[0]]))

        mean_score = np.nan_to_num(np.mean(scores))
        mean_width = np.nan_to_num(np.mean(widths))
        
        if modern:
            # Count the occurrences of the closest_line.id values
            id_counts = Counter([point[1] for point in modern])
            # Find the most common closest_line.id
            most_common_id = id_counts.most_common(1)[0][0]
            # Use a list comprehension to filter the array for the most common id
            filtered_array = [point for point in modern if point[1] == most_common_id]
            # Calculate the mean values of the closest_distance and bearing_difference fields
            mean_distance = sum([point[2] for point in filtered_array]) / len(filtered_array)
            mean_bearing_difference = sum([point[3] for point in filtered_array]) / len(filtered_array)
            
            if mean_bearing_difference < 20 and mean_distance < MAX_MODERN_OFFSET / 1000000: 
                modern_id = most_common_id
            else:
                modern_id = ''
        else:
            modern_id = ''

        if mean_score == 0:
            linestring_attributes.append({'score': 0, 'width': 0, 'modernity': ''})
        else:
            attributes = {'score': int(mean_score*100), 'width': mean_width, 'modernity': modern_id}
            linestring_attributes.append(attributes)
                            
    return [linestring_attributes, modern_linklines]