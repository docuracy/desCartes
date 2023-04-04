'''
@author: Stephen Gadd, Docuracy Ltd, UK

desCartes recognises roads on old maps, and converts them to vector lines that can be 
used in GIS applications and historical transport network analysis.

For any given map extent (bounding coordinates), obsolete_code first generates a a 
georeferenced map image (geotiff), and then processes the image to extract candidate 
road lines. These lines are then filtered, and matched by proximity and orientation 
to modern road vectors. Gaps in the road lines are then filled (and junctions made) 
where appropriate, and each line is assigned a certainty score and (where possible) 
the id of the matching modern road segment.

obsolete_code is pre-configured for use with the National Library of Scotland's 19th-century 
6":1 mile GB Ordnance Survey map tiles served by MapTiler Cloud, and with the modern 
Ordnance Survey Open Roads vector dataset, but might be adapted to suit other maps.

NEXT DEVELOPMENT STEPS: See https://github.com/docuracy/obsolete_code/issues

'''

import rasterio
import cv2
import os
import zipfile
import numpy as np
import warnings
from skimage.morphology import skeletonize
import base64
import shapely.geometry as geometry
from shapely.geometry import MultiLineString, LineString, Point, box
from shapely.ops import transform
import math
import geopandas as gpd
from extract_modern_roads import transform_linestrings
import networkx as nx
from sklearn.cluster import KMeans
# import matplotlib.pyplot as plt # Required only for elbow test
    
def result_image(visualise, map_directory, label, image):
    if visualise:
        thumbnail = cv2.resize(image, (200, int(200 * image.shape[0] / image.shape[1])), interpolation=cv2.INTER_CUBIC)
        fullsize_path = map_directory + label.lower().replace(" ", "_") + '.jpg'
        cv2.imwrite(fullsize_path, image)
        thumbnail_base64 = base64.b64encode(cv2.imencode('.jpg', thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 80])[1]).decode("utf-8")
        return {
            "label": label,
            "url": fullsize_path,
            "thumbnail": thumbnail_base64
            }
        
def zip_files(map_directory, filetype = '.jpg', filename = 'images.zip'):
    jpg_files = [os.path.join(map_directory, f) for f in os.listdir(map_directory) if f.endswith(filetype)]
    zip_path = os.path.join(map_directory, filename)
    with zipfile.ZipFile(zip_path, 'w') as zip_file:
        for jpg_file in jpg_files:
            zip_file.write(jpg_file, os.path.basename(jpg_file))
    
def XY_to_EPSG4326(raster_gdf, raster_transform):
    transformed_coordinates = [transform(lambda x, y: rasterio.transform.xy(raster_transform, y, x), row.geometry) for _, row in raster_gdf.iterrows()]
    EPSG4326_gdf = gpd.GeoDataFrame(geometry=[LineString(line) for line in transformed_coordinates], crs='EPSG:4326')
    EPSG4326_gdf = EPSG4326_gdf.join(raster_gdf.drop('geometry', axis=1))
    return EPSG4326_gdf

def draw_linestrings_on_image(bgr_image, linestring_gdf, linestring_color, linestring_thickness):
    for _, linestring in linestring_gdf.iterrows():
        coords = linestring['geometry'].coords[:]
        pixel_coords = [(int(x), int(y)) for x, y in coords]
        cv2.polylines(bgr_image, [np.array(pixel_coords)], False, linestring_color, thickness=linestring_thickness)
    return bgr_image

def get_nearest_parallel_linestring(gdf, geoindex, test_point, max_distance, tangent_angle, max_angle):
    x, y = test_point.x, test_point.y
    candidate_indices = geoindex.query(box(x - max_distance, y - max_distance, x + max_distance, y + max_distance))
    if len(candidate_indices) < 1:
        return [False,False]
    candidate_distances = [test_point.distance(gdf.geometry.loc[index]) for index in candidate_indices]
    candidates = list(zip(candidate_indices, candidate_distances))
    candidates.sort(key=lambda x: x[1])
    
    for candidate in candidates:
        candidate_id, candidate_distance = gdf.iloc[candidate[0]]['id'], candidate[1]
        if candidate_distance > max_distance:
            continue

        # Get the closest point on the candidate linestring to the test point
        candidate_linestring = gdf.geometry.loc[candidate[0]]
        candidate_closest_point = candidate_linestring.interpolate(candidate_linestring.project(test_point))

        # Get the angle of the candidate linestring's tangent at the closest point
        for offset in [.01, -.01]:
            try:
                candidate_tangent_point = candidate_linestring.interpolate(candidate_linestring.project(candidate_closest_point, normalized=True) + offset) - candidate_closest_point
                break
            except ValueError: # Tried to find tangent using point beyond end of linestring
                continue
        if candidate_tangent_point.is_empty:
            continue
        dx = candidate_tangent_point.x - candidate_closest_point.x
        dy = candidate_tangent_point.y - candidate_closest_point.y
        candidate_angle = math.atan2(dy, dx)

        if min((2 * np.pi) - abs(candidate_angle - tangent_angle), abs(candidate_angle - tangent_angle)) < max_angle:
            return [candidate_distance, candidate_id]

    return [False, False]    

def cut(line, distance): ## https://gist.github.com/sgillies/465156#file_cut.py
    # Cuts a line in two at a distance from its starting point
    if distance <= 0.0 or distance >= line.length:
        print('No cut made: distance = '+str(distance)+', line length = '+str(line.length)+'.')
        return LineString(line), False
    coords = list(line.coords)        
    for i, p in enumerate(coords):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pd = line.project(Point(p))
        print(f'Projecting {p}, got {pd} ...')
        if pd == distance:
            return [
                LineString(coords[:i+1]),
                LineString(coords[i:])]
        if pd > distance or (i == len(coords) - 1 and line.is_closed):
            cp = line.interpolate(distance)
            return [
                LineString(coords[:i] + [(cp.x, cp.y)]),
                LineString([(cp.x, cp.y)] + coords[i:])]
    
def vector_skeleton(skeleton, simplify = 2, discard_length = False, discard_max_points = 1):
    contours = cv2.findContours(skeleton, cv2.RETR_LIST , cv2.CHAIN_APPROX_NONE)[0]
    singular_contours = []
    visited_points = set()
    endpoints = set()
    for contour in contours:
        previouspoint = tuple(contour[0][0])
        visited_points.add(previouspoint)
        endpoints.add(previouspoint)
        current_contour = [[previouspoint]]
        addingpoints = True
        for i in range(1, len(contour) - 1):
            point = tuple(contour[i][0])
            
            if addingpoints:
                if not point in visited_points:
                    current_contour.append([point])
                else:
                    if point in endpoints:
                        current_contour.append([point]) # Line is returning to a previous junction
                    else:
                        endpoints.add(previouspoint) # Line has reversed direction
                    singular_contours.append(np.array(current_contour))
                    addingpoints = False
            else:        
                if not point in visited_points: 
                    endpoints.add(previouspoint) # Line has passed a previous junction
                    current_contour = [[previouspoint], [point]]
                    addingpoints = True
                    
            visited_points.add(point)
            previouspoint = point
            
    ## Break linestrings where they pass through endpoints
    contour_list = singular_contours.copy()    
    split_contours = []
    while contour_list:
        contour = contour_list.pop(0)
        divide = False
        for i in range(1, len(contour) - 1):
            if tuple(contour[i][0]) in endpoints:
                divide = True
                split_contours.append(contour[:i+1])
                contour_list.insert(0, contour[i:])
                break
        if not divide and len(contour) > 1:
            split_contours.append(contour)
    
    lineStrings = []
    for split_contour in split_contours:
        if len(split_contour) <= discard_max_points:
            continue
        lineString = geometry.LineString(np.array(split_contour).reshape(-1, 2)).simplify(simplify)
        if discard_length is not False and lineString.length <= discard_length:
            continue
        lineStrings.append(lineString)
    return lineStrings
        
def extract_dashed_paths(binary_image, dash_detector, std_deviation_multiplier = 3):
    area_range = (dash_detector['area']['mean'] - std_deviation_multiplier * dash_detector['area']['std_dev'], dash_detector['area']['mean'] + std_deviation_multiplier * dash_detector['area']['std_dev'])
    convexity_range = (dash_detector['convexity']['mean'] - std_deviation_multiplier * dash_detector['convexity']['std_dev'], 1)
    aspect_ratio_range = (dash_detector['aspect_ratio']['mean'] - std_deviation_multiplier * dash_detector['aspect_ratio']['std_dev'], dash_detector['aspect_ratio']['mean'] + std_deviation_multiplier * dash_detector['aspect_ratio']['std_dev'])
    contours, _ = cv2.findContours(binary_image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    footpaths = np.zeros_like(binary_image)
    for contour in contours: 
        # Calculate areas of contour and its convex hull
        contour_area = cv2.contourArea(contour)
        if not area_range[0] <= contour_area <= area_range[1]:
            continue
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        convexity = contour_area / hull_area
        if not convexity_range[0] <= convexity <= convexity_range[1]:
            continue
        # Calculate aspect ratio
        rect = cv2.minAreaRect(contour)
        rect_width, rect_height = rect[1]
        if rect_width == 0 or rect_height == 0:
            continue # Reject contour
        else:
            aspect_ratio = min(rect_width, rect_height) / max(rect_width, rect_height)
        if not aspect_ratio_range[0] <= aspect_ratio <= aspect_ratio_range[1]:
            continue
        cv2.drawContours(footpaths, [contour], -1, 255, -1)

    # Dilate to merge double-dash lines    
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (6, 6))
    footpaths_merged = cv2.dilate(footpaths, kernel, iterations=2)
    footpaths_double = cv2.erode(footpaths_merged, kernel, iterations=3)
    footpaths_double = cv2.dilate(footpaths_double, kernel, iterations=4)
    footpaths_single = cv2.subtract(footpaths_merged, footpaths_double)
    footpaths_double = skeletonize(footpaths_double / 255.).astype(np.uint8) * 255
    footpaths_single = skeletonize(footpaths_single / 255.).astype(np.uint8) * 255
    footpaths_double = vector_skeleton(footpaths_double)
    footpaths_single = vector_skeleton(footpaths_single)
    footpaths_double = gpd.GeoDataFrame({'geometry': footpaths_double})
    footpaths_single = gpd.GeoDataFrame({'geometry': footpaths_single})        
    
    return footpaths, footpaths_double, footpaths_single

## TO DO: Investigate why type casting like this causes the server to hang.
# def desCartes(
#     map_directory: str,
#     binary_image: bool = False,
#     blur_size: int = 3,
#     binarization_threshold: int = 210,
#     MAX_ROAD_WIDTH: float = 20.0,
#     MIN_ROAD_WIDTH: int = 6,
#     convexity_min: float = 0.9,
#     min_size_factor: float = 10.0,
#     inflation_factor: float = 2.3,
#     gap_close: float = 20.0,
#     shape_filter: bool = True,
#     templating: bool = True,
#     template_dir: str = './data/templates',
#     template_filenames: list[str] = ['tree-broadleaf.png', 'tree-conifer.png'],
#     thresholds: list[float] = [0.7, 0.7],
#     maximum_tree_density: float = 0.1,
#     visualise: bool = True,
#     show_images: bool = False
#     ):

def desCartes(map_directory,
      binary_image = False, 
      colours = False,
      blur_size = 3, # Used to try to remove blemishes from image - greatly reduces number of spurious contours and consequent processing-time
      binarization_threshold = 210,
      MAX_ROAD_WIDTH = 20, 
      MIN_ROAD_WIDTH = 6, 
      convexity_min = .9, 
      min_size_factor = 10, # Multiplied by int(MAX_ROAD_WIDTH)^2 to give minimum size for a contour to be considered
      inflation_factor = 2.3, # Multiplied by int(MAX_ROAD_WIDTH) to limit average breadth of a contour perpendicular to its skeleton
      gap_close = 20, # For closing gaps between likely roads
      score_min = .1,
      dash_detector = {"area": {"mean": 25.34, "std_dev": 4.98}, "convexity": {"mean": 0.9572, "std_dev": 0.0306}, "aspect_ratio": {"mean": 0.5085, "std_dev": 0.1082}},
      shape_filter = True,
      templating = True,
      template_dir = './data/templates', 
      template_filenames = ['tree-broadleaf.png', 'tree-conifer.png'], 
      thresholds = [.7, .7],
      maximum_tree_density = .1,
      visualise = True,
      show_images = False
      ):
    
    binary_image = bool(binary_image)
    # colours = list(colours)
    blur_size = int(blur_size)
    binarization_threshold = int(binarization_threshold)
    MAX_ROAD_WIDTH = float(MAX_ROAD_WIDTH) 
    MIN_ROAD_WIDTH = int(MIN_ROAD_WIDTH) 
    convexity_min = float(convexity_min) 
    min_size_factor = float(min_size_factor)
    inflation_factor = float(inflation_factor)
    gap_close = float(gap_close)
    score_min = float(score_min)
    dash_detector = dict(dash_detector)
    shape_filter = bool(shape_filter)
    templating = bool(templating)
    template_dir = str(template_dir) 
    template_filenames = list(template_filenames)
    thresholds = list(thresholds)
    maximum_tree_density = float(maximum_tree_density)
    visualise = bool(visualise)
    show_images = bool(show_images)

    # Open the geotiff using rasterio
    with rasterio.open(map_directory + 'geo.tiff') as raster:
        raster_image = raster.read()
        
    ### TESTING
    # return False, False, False, False   
     
    if not colours == False: # Tile source is not GB OS at zoom level 17 (based on size of X-pixel)
        from coloured_roads import coloured_roads
        return coloured_roads(raster_image, map_directory, raster.transform, colours)
    
    modern_roads_EPSG4326, modern_roads = transform_linestrings(map_directory, raster.transform)
    modern_roads_sindex = modern_roads.sindex
    
    grayscale_image = cv2.cvtColor(cv2.merge(raster_image[:3]), cv2.COLOR_BGR2GRAY)
    
    # Initialise visualisation arrays
    visualisation_contoursets = {
        "size": [(127,127,127),.5,[],1], # GREY
        "convexity": [(0,255,0),.3,[],2], # GREEN
        "under-inflation": [(255,0,255),.3,[],2], # PURPLE
        "over-inflation": [(255,255,0),.6,[],2], # TEAL
        "woodland": [(0,255,255),.3,[],2], # YELLOW
        "likely_road_shape": [(0,0,255),.5,[],2] # RED
        } 
    
    print('Finding road contours ...')
    MIN_SIZE = float(min_size_factor) * float(MAX_ROAD_WIDTH) ** 2
    if binary_image is False:
        blurred_grayscale_image = cv2.medianBlur(grayscale_image, int(blur_size)) 
        _, binary_image_otsu = cv2.threshold(grayscale_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU) # Tends to create gaps in road lines
        _, binary_image = cv2.threshold(blurred_grayscale_image, binarization_threshold, 255, cv2.THRESH_BINARY)
    height, width = binary_image.shape[:2]

    result_images = []
    result_images.append(result_image(visualise, map_directory, "Thresholded map image", binary_image))
    
    # Remove blobs (for example, circular markers from roadways on GB OS maps)
    params = cv2.SimpleBlobDetector_Params()
    params.filterByColor =True
    params.blobColor = 0
    params.filterByCircularity = True
    params.maxCircularity = 1
    params.filterByArea = True
    params.maxArea = MAX_ROAD_WIDTH ** 2
    detector = cv2.SimpleBlobDetector_create(params)
    keypoints = detector.detect(binary_image_otsu) # Have to use otsu thresholding because otherwise blobs merge with road boundary lines
    for kp in keypoints:
        x, y = int(kp.pt[0]), int(kp.pt[1])
        r = int(kp.size / 2) + 2
        cv2.circle(binary_image, (x, y), r, (255, 255, 255), -1)
        
    # Remove dashes (which can cause skeleton braiding), and extract both single- and double-dashed lines to GeoDataFrames    
    footpaths, footpaths_double, footpaths_single = extract_dashed_paths(binary_image_otsu, dash_detector)

    footpaths_double_EPSG4326_gdf = XY_to_EPSG4326(footpaths_double, raster.transform)
    footpaths_double_EPSG4326_gdf.to_file(map_directory + 'desCartes.gpkg', layer="double_dashes", driver="GPKG")
    footpaths_single_EPSG4326_gdf = XY_to_EPSG4326(footpaths_single, raster.transform)
    footpaths_single_EPSG4326_gdf.to_file(map_directory + 'desCartes.gpkg', layer="single_dashes", driver="GPKG")
    
    binary_image = np.where(footpaths == 255, 255, binary_image) # Remove dashes

    # Thin all black lines to 1px
    binary_image = np.invert(binary_image)  
    binary_image = skeletonize(binary_image / 255).astype(np.uint8) * 255
    
    # Dilate to close small gaps in road outlines    
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (MIN_ROAD_WIDTH, MIN_ROAD_WIDTH))
    # kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2,2))
    binary_image = cv2.dilate(binary_image, kernel, iterations=1)
    binary_image = np.invert(binary_image)

    contours, hierarchy = cv2.findContours(binary_image, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    # Pre-validate to avoid need to re-validate when considering child contours
    print("Validating contours ...")
    contour_validity = []
    contour_areas = []
    for i, contour in enumerate(contours):
        if len(contour) >= 3:
            area = cv2.contourArea(contour)
            if area >= MIN_SIZE:
                contour_validity.append(True)
            else:
                contour_validity.append(False)
                visualisation_contoursets["size"][2].append(contour) # Grey for size rejection  
            contour_areas.append(area)
        else:
            contour_validity.append(False)
            contour_areas.append(0)   
    
    result_images.append(result_image(visualise, map_directory, "Thinned map image", binary_image))
    
    print("Testing and filtering shapes ...")
    likely_roads = []
    for i, contour in enumerate(contours):
        print("{}/{}".format(i+1, len(contours)))
        
        if not contour_validity[i]:
            continue # Reject contour
        
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        if hull_area == 0:
            continue # Reject contour
        
        if shape_filter == True:
        
            convexity = contour_areas[i] / hull_area
            if convexity > convexity_min:
                visualisation_contoursets["convexity"][2].append(contour) # Green for convexity rejection
                continue # Reject contour      
            
        # Create shape with holes and outsized areas removed
        emmentaler = np.zeros_like(binary_image)
        cv2.drawContours(emmentaler, [contour], -1, 255, -1)        
        child_contours = [c for index, (c, h) in enumerate(zip(contours, hierarchy[0])) if h[3] == i and contour_validity[index]] # Get valid child contours; any blobs within a likely road are thus eliminated
        for child in child_contours:
            cv2.drawContours(emmentaler, [child], -1, 0, -1)
            
        if shape_filter == True:    
            
            emmentaler_area = np.sum(emmentaler == 255)
            ## Remove outsized areas   
            inflation_factor = inflation_factor
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(MAX_ROAD_WIDTH * inflation_factor), int(MAX_ROAD_WIDTH * inflation_factor)))
            emmentaler_eroded = cv2.erode(emmentaler, kernel, iterations=1)
            emmentaler_eroded = np.where(emmentaler_eroded == 0, emmentaler, 0)
            
            emmentaler_contours = cv2.findContours(emmentaler_eroded, cv2.RETR_EXTERNAL , cv2.CHAIN_APPROX_NONE)[0]
            
            double_roadwidth = (MAX_ROAD_WIDTH + MIN_ROAD_WIDTH)
            expected_road_perimeter = double_roadwidth + (4 * contour_areas[i] / double_roadwidth)
            inflation = cv2.arcLength(emmentaler_contours[0], True) * double_roadwidth / expected_road_perimeter
            if inflation < double_roadwidth / inflation_factor:
                visualisation_contoursets["under-inflation"][2].append(contour) # Purple for under-inflation rejection
                continue # Reject contour
            elif inflation > double_roadwidth * inflation_factor:
                visualisation_contoursets["over-inflation"][2].append(contour) # Teal for over-inflation rejection
                continue # Reject contour                
            
            if templating == True: # (Woodland templates rather than road templates)
                
                ## Try testing woodland density using matchTemplate
                mask = emmentaler.astype(bool)
                masked_image = grayscale_image * mask[:, :]
                x, y, w, h = cv2.boundingRect(contour)
                masked_image = masked_image[y:y+h, x:x+w]
                match_count = 0
                for i, template_filename in enumerate(template_filenames):
                    # print("Matching: "+template_filename)
                    template = cv2.imread(f"{template_dir}/{template_filename}", 0)
                    res = cv2.matchTemplate(masked_image, template, cv2.TM_CCOEFF_NORMED)
                    match_count += np.count_nonzero(res >= thresholds[i])
                    template_area = template.shape[0] * template.shape[1]
                # print("Tree density: " + str(match_count * template_area / emmentaler_area))
                if match_count * template_area / emmentaler_area > maximum_tree_density:
                    visualisation_contoursets["woodland"][2].append(contour) # Yellow for tree density rejection
                    continue # Reject contour    
                    
                likely_roads.append(emmentaler_eroded)
        
        else:
            likely_roads.append(emmentaler)      
        
        visualisation_contoursets["likely_road_shape"][2].append(contour)# Red for likely road  
            
    print(str(len(likely_roads)) + ' candidate road areas found.')
    
    if len(likely_roads) == 0:
        return contours, False, result_images, False, 'No candidate road areas found.'
    
    likely_roads = sum(likely_roads)
    
    # ## Next, dilate/erode to close any *small* gaps in road sections
    # print("Dilating ...")
    # kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gap_close, gap_close))
    # likely_roads = cv2.dilate(likely_roads, kernel, iterations=1)        
    
    ## Skeletonize
    print("Skeletonizing ...")
    skeleton = skeletonize(likely_roads / 255.).astype(np.uint8) * 255
    if visualise:
        likely_roads_visualisation = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2BGRA)
        overlay = np.zeros((height, width, 4), dtype=np.uint8)
        shape = overlay.copy()
        shape[likely_roads == 255, 1:4] = 255
        # overlay[:] = np.array([0, 0, 255, 255], dtype=np.uint8) # Red
        shaded = cv2.addWeighted(overlay, .5, likely_roads_visualisation, .5, 0) # Set opacity
        likely_roads_visualisation = np.where(shape == 255, shaded, likely_roads_visualisation) # Draw shading
        skeleton_mask = np.zeros_like(grayscale_image, dtype=np.uint8)
        skeleton_mask[skeleton == 255] = 255
        likely_roads_visualisation[skeleton_mask > 0] = (0, 255, 255, 255)
        result_images.append(result_image(visualise, map_directory, "Skeletonized candidate roads", likely_roads_visualisation))

#######################
## VECTOR PROCESSING ##
#######################
    
    ## Divide contours (which are coincident loops) into single lines, starting a new line at each junction
    print("Dividing contours ...")
    
    lineStrings = vector_skeleton(skeleton)

#####################
## VECTOR ANALYSIS ##
#####################
    
    ## Measure the proximity of modern roads and likely road edges at sample points along each lineString,
    ## and split lineStrings between test points where the road edge test result changes.
    print("Measuring proximities ...")
    split_lineStrings = []
    tests = []
    proximity_visualisation = cv2.cvtColor(binary_image, cv2.COLOR_GRAY2BGR)
    proximity_visualisation = draw_linestrings_on_image(proximity_visualisation, modern_roads, linestring_color = (0, 255, 255), linestring_thickness = 3)
    for lineString in lineStrings:
        lineString_residue = lineString
        tests.append([])
        testLength = lineString.length - MAX_ROAD_WIDTH # Do not test in proximity to junctions
        if testLength <= 0:
            tests[-1].append({'testLength': False})
            split_lineStrings.append(lineString_residue)
            continue
        test_point_count = max(2, 1 + math.ceil(testLength / MAX_ROAD_WIDTH)) #  Test at least every MAX_ROAD_WIDTH pixels
        interval_length = testLength / (test_point_count - 1)
        previouspoint = lineString.interpolate(MAX_ROAD_WIDTH / 4)
        previous_road_test = None
        total_split_distance = 0
        # Iterate over the intervals and find the normal_vector at each one
        for i in range(test_point_count):
            tests[-1].append({'testLength': False, 'modern_road_distance': False, 'modern_road_id': False, 'road_boundaries': []})
            test_distance = - total_split_distance + MAX_ROAD_WIDTH / 2 + interval_length * i
            tests[-1][-1]['testLength'] = test_distance
            test_point = lineString_residue.interpolate(test_distance)
            cv2.circle(proximity_visualisation, (int(test_point.x), int(test_point.y)), 4, (0, 0, 255), -1)
            tangent_angle = np.arctan2(test_point.y - previouspoint.y, test_point.x - previouspoint.x)
            tests[-1][-1]['modern_road_distance'], tests[-1][-1]['modern_road_id'] = get_nearest_parallel_linestring(modern_roads, modern_roads_sindex, test_point, 3 * MAX_ROAD_WIDTH, tangent_angle, max_angle = 15 * np.pi / 180)
            normal_angle = np.pi/2 + tangent_angle
            normal_vector = np.array([-np.cos(normal_angle), np.sin(normal_angle)])
    
            # Test the binary image at points along the normal vector
            for sign in [-1, 1]:
                tests[-1][-1]['road_boundaries'].append(False)
                for d in range(math.ceil(MAX_ROAD_WIDTH / 2)):
                    offset_pixel = (int(round(test_point.x + sign * d * normal_vector[0])), int(round(test_point.y - sign * d * normal_vector[1])))
                    cv2.circle(proximity_visualisation, (int(offset_pixel[0]), int(offset_pixel[1])), 2, (0, 255, 0), -1)
                    if offset_pixel[0] >= 0 and offset_pixel[0] < binary_image.shape[1] and offset_pixel[1] >= 0 and offset_pixel[1] < binary_image.shape[0] and binary_image[offset_pixel[1],offset_pixel[0]] == 0:
                        # likely_road += 1
                        tests[-1][-1]['road_boundaries'][-1] = d
                        break
            previouspoint = test_point
            
            road_test = tests[-1][-1]['road_boundaries'][0] is not False and tests[-1][-1]['road_boundaries'][1] is not False and sum(tests[-1][-1]['road_boundaries']) + 1 >= MIN_ROAD_WIDTH
            if i > 1 and not previous_road_test == road_test: # Split the lineString
                split_distance = tests[-1][-1]['testLength'] - interval_length / 2
                total_split_distance += split_distance
                lineString_first_part, lineString_residue = cut(lineString_residue, split_distance)
                split_lineStrings.append(lineString_first_part)
                last_test = tests[-1].pop()
                tests.append([last_test])
            previous_road_test = road_test
        split_lineStrings.append(lineString_residue)
     
    print(str(len(split_lineStrings)-len(lineStrings)) + ' splits made ...')
    lineStrings = split_lineStrings       
        
    result_images.append(result_image(visualise, map_directory, "Road boundary checks (with modern OS roads)", proximity_visualisation))

#############
## SCORING ##
#############
    
    print("Scoring " + str(len(lineStrings)) + " candidate roads ...")
    scores = []
    modern_road_labels = []
    for lineString, test_set in zip(lineStrings, tests):
        modern_road_labels.append([])
        if len(test_set) == 0:
            scores.append(0)
            continue
        elif len(test_set) == 1 and test_set[0]['testLength'] == False: # LineString was too short to assess
            scores.append(.3)
            continue
        count = 0
        for test in test_set:
            modern_road_labels[-1].append(test['modern_road_id'])
            if test['road_boundaries'][0] is not False and test['road_boundaries'][1] is not False and sum(test['road_boundaries']) + 1 >= MIN_ROAD_WIDTH: # Road lines on both sides
                count += 1 if test['modern_road_distance'] is not False else .7
        
        non_circularity = Point(lineString.coords[0]).distance(Point(lineString.coords[-1])) / lineString.length
        
        scores.append(count * non_circularity / len(test_set))   
            
    # Concatenate unique non-False modern road ids
    modern_road_labels = ['; '.join(set(str(item) for item in row if item)) for row in modern_road_labels]  
           
    # Combine arrays in a GeoDataFrame
    candidate_roads = gpd.GeoDataFrame({'geometry': lineStrings, 'modern_road_id': modern_road_labels, 'score': scores})
    candidate_roads = candidate_roads[candidate_roads['score'] >= score_min].reset_index(drop=True) # Remove low-scoring candidate roads
    print('... ' + str(len(lineStrings)-len(candidate_roads)) + ' low-scoring candidate roads removed.')

    print("Assessing connectivity ...")
    
    '''
    The following section aims to identify clusters of interconnected linestrings from a set of linestrings 
    represented as a GeoDataFrame. The clustering is based on the gravity score of each group of linestrings, 
    which is calculated by summing the length of each linestring in the group multiplied by its quality score, 
    and weighting the result by the proportion of the total length squared represented by the group. The 
    optimal number of clusters is determined using the elbow method. The code then creates a new GeoDataFrame 
    of unconnected linestring endpoints, and creates filler connections between groups of linestrings with 
    high enough gravity scores based on the distance between all unconnected endpoints in the two groups. A 
    graph is used to check that the gap is not met by the existing network. Otherwise, if a gap between two 
    endpoints meets the gravity_threshold and gap_close tests, the code creates a new filler road between 
    the two endpoints.
    '''
    
    # Create a graph of interconnected linestrings
    G = nx.Graph()
    gdf_sindex = candidate_roads.sindex
    for i, row_i in candidate_roads.iterrows():
        possible_matches_index = list(gdf_sindex.intersection(row_i['geometry'].bounds))
        possible_matches = candidate_roads.iloc[possible_matches_index]
        for j, row_j in possible_matches.iterrows():
            if i == j:
                continue
            if row_i['geometry'].touches(row_j['geometry']):
                G.add_edge(i, j)
    
    # Identify the groups of interconnected linestrings
    print("Grouping candidate roads ...")
    groups = list(nx.connected_components(G))
    
    # Set the maximum total length squared
    max_total_length_squared = sum([candidate_roads.geometry.length.max()**2 for _ in range(len(groups))])
    
    # Calculate the gravity score for each group
    print("Calculating gravity scores ...")
    group_gravity_scores = []
    for group in groups:
        length_score_sum = 0.0
        total_length_squared = 0.0
        for i in group:
            length = candidate_roads.iloc[i]['geometry'].length
            score = candidate_roads.iloc[i]['score']
            length_score_sum += length * score
            total_length_squared += length ** 2
        length_factor = min(total_length_squared / max_total_length_squared, 1.0)
        group_gravity_scores.append([length_score_sum * length_factor])
    
    # # Determine the optimal number of clusters using the elbow method
    # print("Elbowing ...")    
    # elbow_scores = []
    # for k in range(1, 11):
    #     kmeans = KMeans(n_clusters=k)
    #     kmeans.fit(group_gravity_scores)
    #     elbow_scores.append(kmeans.inertia_)
    # plt.plot(range(1, 11), elbow_scores)
    # plt.xlabel('Number of clusters')
    # plt.ylabel('Elbow score')
    # plt.show()
    
    # Based on the plot, choose the number of clusters and fit the model
    print("Clustering ...")
    n_clusters = 2  # determined by elbowing
    kmeans = KMeans(n_clusters=n_clusters)
    kmeans.fit(group_gravity_scores)
    
    # Get the cluster labels and centroids
    centroids = kmeans.cluster_centers_
    
    # Assign the appropriate gravity threshold based on the cluster centroids
    gravity_threshold = max(centroids)
    
    # Find unconnected endpoints in groups with gravity_score >= gravity_threshold
    print("Gathering unconnected endpoints with sufficient gravity for filler segments ...")
    G = nx.Graph()
    endpoints = set()
    connected_endpoints = set()
    road_network_segments = []
    
    for group, gravity_score in zip(groups, group_gravity_scores):
        if gravity_score >= gravity_threshold:
            group_lines = candidate_roads.iloc[list(group)]
            for _, row in group_lines.iterrows():
                line = row['geometry']
                modern_road_id = row['modern_road_id']
                start_node_coords = tuple(line.coords[0])
                end_node_coords = tuple(line.coords[-1])
                G.add_node(start_node_coords)
                G.add_node(end_node_coords)
                G.add_edge(start_node_coords, end_node_coords, length=line.length, linestring=line)
                for endpoint in [line.coords[0], line.coords[-1]]:
                    if endpoint not in endpoints:
                        endpoints.add(endpoint)
                    else:
                        connected_endpoints.add(endpoint)
                road_network_segments.append({
                    'geometry': line,
                    'modern_road_id': modern_road_id
                })
            
    unconnected_endpoints = endpoints - connected_endpoints
    endpoint_gdf = gpd.GeoDataFrame.from_records([{'geometry': Point(endpoint)} for endpoint in unconnected_endpoints])
    print('... found ' + str(len(unconnected_endpoints)) + ' such endpoints ...')
    
    # Create filler connections (up to gap_close in length) between and within groups with high enough gravity scores
    endpoint_sindex = endpoint_gdf.sindex
    filler_count = 0
    
    for i, endpoint1 in endpoint_gdf.iterrows():
        possible_matches_index = list(endpoint_sindex.intersection(endpoint1.geometry.buffer(gap_close).bounds))
        possible_matches = endpoint_gdf.iloc[possible_matches_index]
        for j, endpoint2 in possible_matches.iterrows():
            if i == j:
                continue # Cannot fill between identical points
            if nx.shortest_path_length(G, tuple(endpoint1.geometry.coords[0]), tuple(endpoint2.geometry.coords[0]), weight='length') < 3 * gap_close:
                continue # Do not create filler if a short path already exists
            road_network_segments.append({
                'geometry': LineString([endpoint1.geometry, endpoint2.geometry]),
                'modern_road_id': '-filler segment-'
            })
            filler_count += 1
    
    road_network_gdf = gpd.GeoDataFrame.from_records(road_network_segments)
    
    print("... " + str(filler_count) + " fillers created ...")
    
    # Reproject LineStrings to original raster CRS
    print("Reprojecting ...")
    
    candidate_roads_EPSG4326_gdf = XY_to_EPSG4326(candidate_roads, raster.transform)
    candidate_roads_EPSG4326_gdf['modern_road_id'] = candidate_roads['modern_road_id'].values
    candidate_roads_EPSG4326_gdf['score'] = candidate_roads['score'].values
    candidate_roads_EPSG4326_gdf.to_file(map_directory + 'desCartes.gpkg', layer="candidate_roads", driver="GPKG")
    
    road_network_EPSG4326_gdf = XY_to_EPSG4326(road_network_gdf, raster.transform)
    road_network_EPSG4326_gdf['modern_road_id'] = road_network_gdf['modern_road_id'].values
    road_network_EPSG4326_gdf.to_file(map_directory + 'desCartes.gpkg', layer="road_network", driver="GPKG")
     
###################
## VISUALISATION ##
###################
    
    if visualise:
        print("Visualising ...")
        
        visualisation = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2BGRA)
        for _, visualisation_contourset in visualisation_contoursets.items():
            overlay = np.zeros((height, width, 4), dtype=np.uint8)
            shape = overlay.copy()
            cv2.drawContours(shape, visualisation_contourset[2], -1, (255,255,255,255), -1) # Create mask for shading
            overlay[:] = np.concatenate([np.array(visualisation_contourset[0], dtype=np.uint8), [255]]) # Add colour
            shaded = cv2.addWeighted(overlay, visualisation_contourset[1], visualisation, 1 - visualisation_contourset[1], 0) # Set opacity
            visualisation = np.where(shape == 255, shaded, visualisation) # Draw shading
            cv2.drawContours(visualisation, visualisation_contourset[2], -1, visualisation_contourset[0], visualisation_contourset[3]) # Draw outlines
        
        candidate_road_dict = {}
        for i, row in candidate_roads.iterrows():
            score = row['score']
            candidate_road = row['geometry']
            if score != 0:
                if score not in candidate_road_dict:
                    candidate_road_dict[score] = []
                candidate_road_dict[score].append(candidate_road)
        
        for score, candidate_roads_group in candidate_road_dict.items():
            overlay = visualisation.copy()
            colour = (255, 0, 0) if score == -1 else (0, 255, 255) # Blue for filler roads
            score = .5 if score == -1 else score # Filler roads
            opacity = np.sin(score * np.pi / 2) # shape the score profile
            for candidate_road in candidate_roads_group:
                coords = np.array(candidate_road.coords, np.int32)
                coords = coords.reshape(-1, 1, 2)
                cv2.polylines(overlay, [coords], isClosed=False, color=colour, thickness=2)
            visualisation = cv2.addWeighted(overlay, opacity, visualisation, 1 - opacity, 0)
    
        result_images.append(result_image(visualise, map_directory, "Segmented map image", visualisation))
        
        road_network_visualisation = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2BGR)
        road_network_visualisation = draw_linestrings_on_image(road_network_visualisation, road_network_gdf, (0, 0, 255, 255), 2)
        result_images.append(result_image(visualise, map_directory, "Predicted Road Network", road_network_visualisation))
                    
        zip_files(map_directory, '.jpg', 'images.zip')
                
        if show_images:
            print(str(len(result_images)) + ' result images saved.')
            print('Showing images ...')
            cv2.imshow("Binary Image", binary_image)
            cv2.imshow('skeleton', skeleton) 
            cv2.imshow('likely_roads_visualisation', likely_roads_visualisation) 
            cv2.imshow('proximity_visualisation', proximity_visualisation) 
            cv2.imshow('candidate_roads', visualisation) 
            cv2.imshow('road_network', road_network_visualisation) 
            cv2.waitKey(0)
    
    print('... completed.')
    return contours, skeleton, result_images, ''