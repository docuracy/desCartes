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
import numpy as np
from skimage.morphology import skeletonize
import base64
import shapely.geometry as geometry
from shapely.geometry import MultiLineString, LineString, Point, box
from shapely.ops import transform
import math
import geopandas as gpd
from extract_modern_roads import transform_linestrings
import io
import networkx as nx
from sklearn.cluster import KMeans
# import matplotlib.pyplot as plt # Required only for elbow test

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
        dx = candidate_tangent_point.x - candidate_closest_point.x
        dy = candidate_tangent_point.y - candidate_closest_point.y
        candidate_angle = math.atan2(dy, dx)

        if min((2 * np.pi) - abs(candidate_angle - tangent_angle), abs(candidate_angle - tangent_angle)) < max_angle:
            return [candidate_distance, candidate_id]

    return [False, False]    

def desCartes(map_directory,
              binary_image = "False", 
              blur_size = "3", # Used to try to remove blemishes from image - greatly reduces number of spurious contours and consequent processing-time
              binarization_threshold = "210",
              MAX_ROAD_WIDTH = "20", 
              MIN_ROAD_WIDTH = "6", 
              convexity_min = ".9", 
              min_size_factor = "10", # Multiplied by int(MAX_ROAD_WIDTH)^2 to give minimum size for a contour to be considered
              inflation_factor = "2.3", # Multiplied by int(MAX_ROAD_WIDTH) to limit average breadth of a contour perpendicular to its skeleton
              gap_close = "20", # For closing gaps between likely roads
              shape_filter = "True",
              templating = "True",
              template_dir = './data/templates', 
              template_filenames = ['tree-broadleaf.png', 'tree-conifer.png'], 
              thresholds = [.7, .7],
              maximum_tree_density = ".1",
              visualise = "True",
              show_images = "False",
              connectivity_max = "40", # Distance from the endpoints of other candidate roads below which a candidate road will be rejected
              connectivity_score_min = ".2" # Connectivity considered only between candidate roads with at least this score
              ):
    
    # Necessary to handle parameters passed as strings in URL
    def cast_params(binary_image, blur_size, binarization_threshold, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, 
        convexity_min, min_size_factor, inflation_factor, gap_close, maximum_tree_density, 
        shape_filter, templating, visualise, show_images, connectivity_max, connectivity_score_min):
        binary_image = False if binary_image == "False" else True
        blur_size = int(blur_size) if isinstance(blur_size, str) else blur_size
        binarization_threshold = int(binarization_threshold) if isinstance(binarization_threshold, str) else binarization_threshold
        MAX_ROAD_WIDTH = int(MAX_ROAD_WIDTH) if isinstance(MAX_ROAD_WIDTH, str) else MAX_ROAD_WIDTH
        MIN_ROAD_WIDTH = int(MIN_ROAD_WIDTH) if isinstance(MIN_ROAD_WIDTH, str) else MIN_ROAD_WIDTH
        convexity_min = float(convexity_min) if isinstance(convexity_min, str) else convexity_min
        min_size_factor = float(min_size_factor) if isinstance(min_size_factor, str) else min_size_factor
        inflation_factor = float(inflation_factor) if isinstance(inflation_factor, str) else inflation_factor
        gap_close = int(gap_close) if isinstance(gap_close, str) else gap_close
        maximum_tree_density = float(maximum_tree_density) if isinstance(maximum_tree_density, str) else maximum_tree_density
        shape_filter = False if shape_filter == "False" else True
        templating = False if templating == "False" else True
        visualise = False if visualise == "False" else True
        show_images = False if show_images == "False" else True
        connectivity_max = float(connectivity_max) if isinstance(connectivity_max, str) else connectivity_max
        connectivity_score_min = float(connectivity_score_min) if isinstance(connectivity_score_min, str) else connectivity_score_min
        return binary_image, blur_size, binarization_threshold, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, convexity_min, min_size_factor, inflation_factor, gap_close, maximum_tree_density, shape_filter, templating, visualise, show_images, connectivity_max, connectivity_score_min

    binary_image, blur_size, binarization_threshold, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, convexity_min, min_size_factor, inflation_factor, gap_close, maximum_tree_density, shape_filter, templating, visualise, show_images, connectivity_max, connectivity_score_min = cast_params(binary_image, blur_size, binarization_threshold, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, convexity_min, min_size_factor, inflation_factor, gap_close, maximum_tree_density, shape_filter, templating, visualise, show_images, connectivity_max, connectivity_score_min)
    
    # Open the geotiff using rasterio
    with rasterio.open(map_directory + 'geo.tiff') as raster:
        raster_image = raster.read()
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
    MIN_SIZE = min_size_factor * MAX_ROAD_WIDTH ** 2
    if binary_image is False:
        blurred_grayscale_image = cv2.medianBlur(grayscale_image, blur_size) 
        # binary_image = cv2.threshold(grayscale_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1] # Tends to create gaps in road lines
        _, binary_image = cv2.threshold(blurred_grayscale_image, binarization_threshold, 255, cv2.THRESH_BINARY)
    height, width = binary_image.shape[:2]

    base64_images = []
    if visualise:
        base64_images.append({"label": "Thresholded map image", "image": base64.b64encode(cv2.imencode('.jpg', binary_image)[1]).decode("utf-8")})      
    
    '''
    TO DO: Before thinning the image, optionally detect dashed line contours using std_deviation_multiplier, area_range, 
    convexity_range, and aspect_ratio_range defined in map_defaults.json. Use morphological operations to 
    generate line contours which might represent footpaths (return these as a separate gpkg). The delete the dash 
    contours from the binary_image: it is more effective at this stage than merely filtering by size after 
    thinning the image, and useful for reducing the braiding otherwise evident on the skeletonized candidate roads image.
    
    The morphological operations for extracting potential footpaths would be:
    
    1. Draw dash contours in white on black
    2. Dilate to merge dashes and parallel lines
    3. Skeletonize and then get contours
    4. Reduce contours to single linestrings (as later in this code).
    5. Get single-dash lines (potentially footpaths running along solid boundaries) by eroding the dilated image until they disappear, then subtract from the dilated image
    6. Skeletonize and contour as before. Such contours would align with the dashes rather than the centre of such a footpath.
    
    '''
         
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
    
    if visualise:
        base64_images.append({"label": "Thinned map image", "image": base64.b64encode(cv2.imencode('.jpg', binary_image)[1]).decode("utf-8")})
    
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
        return contours, False, base64_images, False, 'No candidate road areas found.'
    
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
        base64_images.append({"label": "Skeletonized candidate roads", "image": base64.b64encode(cv2.imencode('.jpg', likely_roads_visualisation)[1]).decode("utf-8")})

#######################
## VECTOR PROCESSING ##
#######################
    
    ## Divide contours (which are coincident loops) into single lines, starting a new line at each junction
    print("Dividing contours ...")
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
        lineStrings.append(geometry.LineString(np.array(split_contour).reshape(-1, 2)).simplify(2))

#####################
## VECTOR ANALYSIS ##
#####################
    
    ## Measure the proximity of modern roads and likely road edges at sample points along each lineString
    print("Measuring proximities ...")
    modern_road_labels = []
    proximity_visualisation = cv2.cvtColor(binary_image, cv2.COLOR_GRAY2BGR)
    proximity_visualisation = draw_linestrings_on_image(proximity_visualisation, modern_roads, linestring_color = (0, 255, 255), linestring_thickness = 3)
    proximity = []
    for lineString in lineStrings:
        proximity.append([])
        modern_road_labels.append([])
        testLength = lineString.length - MAX_ROAD_WIDTH # Do not test in proximity to junctions
        if testLength <= 0:
            proximity[-1].append(["Too short: "+str(lineString.length)])
            continue
        test_point_count = max(2, 1 + math.ceil(testLength / MAX_ROAD_WIDTH)) #  Test at least every MAX_ROAD_WIDTH pixels
        interval_length = testLength / (test_point_count - 1)
        previouspoint = lineString.interpolate(MAX_ROAD_WIDTH / 4)
        # Iterate over the intervals and find the normal_vector at each one
        for i in range(test_point_count):
            test_distance = MAX_ROAD_WIDTH / 2 + interval_length * i
            proximity[-1].append([test_distance])
            test_point = lineString.interpolate(test_distance)
            cv2.circle(proximity_visualisation, (int(test_point.x), int(test_point.y)), 4, (0, 0, 255), -1)
            tangent_angle = np.arctan2(test_point.y - previouspoint.y, test_point.x - previouspoint.x)
            proximity[-1][-1].extend(get_nearest_parallel_linestring(modern_roads, modern_roads_sindex, test_point, 3 * MAX_ROAD_WIDTH, tangent_angle, max_angle = 15 * np.pi / 180))
            modern_road_labels[-1].append(proximity[-1][-1][-1])
            normal_angle = np.pi/2 + tangent_angle
            normal_vector = np.array([-np.cos(normal_angle), np.sin(normal_angle)])
    
            # Test the binary image at points along the normal vector
            for sign in [-1, 1]:
                proximity[-1][-1].append(False)
                for d in range(math.ceil(MAX_ROAD_WIDTH / 2)):
                    offset_pixel = (int(round(test_point.x + sign * d * normal_vector[0])), int(round(test_point.y - sign * d * normal_vector[1])))
                    cv2.circle(proximity_visualisation, (int(offset_pixel[0]), int(offset_pixel[1])), 2, (0, 255, 0), -1)
                    if offset_pixel[0] >= 0 and offset_pixel[0] < binary_image.shape[1] and offset_pixel[1] >= 0 and offset_pixel[1] < binary_image.shape[0] and binary_image[offset_pixel[1],offset_pixel[0]] == 0:
                        # likely_road += 1
                        proximity[-1][-1][-1] = d
                        break
            previouspoint = test_point
            
    # Concatenate unique non-False modern road ids
    modern_road_labels = ['; '.join(set(str(item) for item in row if item)) for row in modern_road_labels]
    
    '''
    TO DO: Divide and delete continuous sections of lineStrings that have failed to meet the road boundary test
    
    '''

        
    if visualise:
        base64_images.append({"label": "Road boundary checks (with modern OS roads)", "image": base64.b64encode(cv2.imencode('.jpg', proximity_visualisation)[1]).decode("utf-8")})
    
    # # Split at modern road boundaries and label any matched candidate roads - NOT ASSIGNING MODERN ROAD LABELS PROPERLY TO SPLIT SECTIONS
    # print("Splitting " + str(len(lineStrings)) + " candidate roads at modern road boundaries ...")
    # split_lineStrings = []
    # split_proximity = []
    # modern_road_labels = []
    # for lineString, prox in zip(lineStrings, proximity):
    #     residue_lineString = lineString
    #     residue_prox = prox
    #
    #     i = 1
    #     while i < len(residue_prox):
    #         if residue_prox[i][2] != residue_prox[i-1][2]:
    #             # Split the linestring at the midpoint between consecutive test points where a change in the modern road id is detected
    #             mid_point_distance = (residue_prox[i][0] + residue_prox[i-1][0]) / 2
    #             split_point = residue_lineString.interpolate(mid_point_distance)
    #             points_before_split_point = [point for point in residue_lineString.coords if residue_lineString.project(Point(point)) < mid_point_distance]
    #             used_points = len(points_before_split_point)
    #             split_lineStrings.append(LineString([*points_before_split_point, split_point]))
    #             residue_lineString = LineString([split_point, *residue_lineString.coords[used_points:]])
    #             split_proximity.append(residue_prox[:i])
    #             modern_road_labels.append('' if residue_prox[i-1][2] == False else residue_prox[i-1][2])
    #             residue_prox = residue_prox[i:]
    #             for residue_p in residue_prox:
    #                 residue_p[0] -= mid_point_distance
    #             if len(residue_prox) > 1:
    #                 i = 0
    #         i += 1
    #
    #     split_lineStrings.append(residue_lineString)
    #     split_proximity.append(residue_prox)
    #     modern_road_labels.append('' if (not isinstance(residue_prox[0][0], bool) or residue_prox[0][2] == False) else residue_prox[0][2])
    #
    # lineStrings = split_lineStrings
    # proximity = split_proximity

#############
## SCORING ##
#############
    
    print("Scoring " + str(len(lineStrings)) + " candidate roads ...")
    scores = []
    for lineString, prox in zip(lineStrings, proximity):
        if len(prox) == 0:
            scores.append(0)
            continue
        elif len(prox) == 1 and not isinstance(prox[0], bool): # LineString was too short to assess
            scores.append(.3)
            continue
        count = 0
        for subarr in prox:
            if subarr[3] is not False and subarr[4] is not False and subarr[3] + subarr[4] + 1 >= MIN_ROAD_WIDTH: # Road lines on both sides
                count += 1 if subarr[1] is not False else .7 # Modern road proximity
        
        non_circularity = Point(lineString.coords[0]).distance(Point(lineString.coords[-1])) / lineString.length
        
        scores.append(count * non_circularity / len(prox))     
           
    # Combine arrays in a GeoDataFrame
    candidate_roads = gpd.GeoDataFrame({'geometry': lineStrings, 'modern_road_id': modern_road_labels, 'score': scores})

    # Now assess connectivity of each candidate road by finding the minimum distance of either of its endpoints to the endpoint of 
    # any other candidate road which has a score greater than connectivity_score_min.
    # This method should probably be combined with - or replaced by - some other method which assesses the product of scores and 
    # lengths of interconnected lines.
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
    
    def XY_to_EPSG4326(raster_gdf):
        transformed_coordinates = [transform(lambda x, y: rasterio.transform.xy(raster.transform, y, x), row.geometry) for _, row in raster_gdf.iterrows()]
        EPSG4326_gdf = gpd.GeoDataFrame(geometry=[MultiLineString([line]) for line in transformed_coordinates])
        return EPSG4326_gdf
    
    candidate_roads_EPSG4326_gdf = XY_to_EPSG4326(candidate_roads)
    candidate_roads_EPSG4326_gdf['modern_road_id'] = candidate_roads['modern_road_id'].values
    candidate_roads_EPSG4326_gdf['score'] = candidate_roads['score'].values
    candidate_roads_EPSG4326_gdf.to_file(map_directory + 'candidate_roads.gpkg', layer="candidate_roads", driver="GPKG")
    
    road_network_EPSG4326_gdf = XY_to_EPSG4326(road_network_gdf)
    road_network_EPSG4326_gdf['modern_road_id'] = road_network_gdf['modern_road_id'].values
    road_network_EPSG4326_gdf.to_file(map_directory + 'road_network.gpkg', layer="road_network", driver="GPKG")
    
    # Create a GeoPackage
    print('Creating Downloadable GeoPackage ...')
    buffer = io.BytesIO()
    road_network_EPSG4326_gdf.to_file(buffer, driver="GPKG", layer="candidate_roads", vfs="mem", encoding="utf-8")
    vector_json = {"gpkg": base64.b64encode(buffer.getvalue()).decode('utf-8')}
     
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
    
        base64_images.append({"label": "Segmented map image", "image": base64.b64encode(cv2.imencode('.jpg', visualisation)[1]).decode("utf-8")}) 
        
        road_network_visualisation = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2BGR)
        road_network_visualisation = draw_linestrings_on_image(road_network_visualisation, road_network_gdf, (0, 0, 255, 255), 2)
        base64_images.append({"label": "Predicted Road Network", "image": base64.b64encode(cv2.imencode('.jpg', road_network_visualisation)[1]).decode("utf-8")})
                
        if show_images:
            print('Showing images ...')
            cv2.imshow("Binary Image", binary_image)
            cv2.imshow('skeleton', skeleton) 
            cv2.imshow('likely_roads_visualisation', likely_roads_visualisation) 
            cv2.imshow('proximity_visualisation', proximity_visualisation) 
            cv2.imshow('candidate_roads', visualisation) 
            cv2.imshow('road_network', road_network_visualisation) 
            cv2.waitKey(0)
    
    print('... completed.')
    return contours, skeleton, base64_images, vector_json, ''