'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''

import rasterio
import cv2
import numpy as np
from skimage.morphology import skeletonize
import base64
import shapely.geometry as geometry
from shapely.geometry import MultiLineString, LineString, Point
from shapely.ops import split, transform
import math
import geopandas as gpd
from itertools import combinations
from extract_modern_roads import transform_linestrings

def draw_linestrings_on_image(bgr_image, linestring_gdf, linestring_color, linestring_thickness):
    for _, linestring in linestring_gdf.iterrows():
        coords = linestring['geometry'].coords[:]
        pixel_coords = [(int(x), int(y)) for x, y in coords]
        cv2.polylines(bgr_image, [np.array(pixel_coords)], False, linestring_color, thickness=linestring_thickness)
    return bgr_image

def road_contours(map_directory,
                  binary_image = "False", 
                  blur_size = "3", # Used to try to remove blemishes from image - greatly reduces number of spurious contours and consequent processing-time
                  binarization_threshold = "210",
                  MAX_ROAD_WIDTH = "20", 
                  MIN_ROAD_WIDTH = "6", 
                  convexity_min = ".9", 
                  min_size_factor = "10", # Multiplied by int(MAX_ROAD_WIDTH)^2 to give minimum size for a contour to be considered
                  inflation_factor = "2.3", # Multiplied by int(MAX_ROAD_WIDTH) to limit average breadth of a contour perpendicular to its skeleton
                  gap_close = "20", # For closing gaps between likely roads
                  templating = "True",
                  template_dir = './data/templates', 
                  template_filenames = ['tree-broadleaf.png', 'tree-conifer.png'], 
                  thresholds = [.7, .7],
                  maximum_tree_density = ".1",
                  visualise = "True",
                  show_images = "False"
                  ):
    
    # Necessary to handle parameters passed as strings in URL
    def cast_params(binary_image, blur_size, binarization_threshold, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, 
                convexity_min, min_size_factor, inflation_factor, gap_close, maximum_tree_density, 
                visualise, show_images):
                binary_image = False if binary_image == "False" else True
                blur_size = int(blur_size)
                binarization_threshold = int(binarization_threshold)
                MAX_ROAD_WIDTH = int(MAX_ROAD_WIDTH)
                MIN_ROAD_WIDTH = int(MIN_ROAD_WIDTH)
                convexity_min = float(convexity_min)
                min_size_factor = int(min_size_factor)
                inflation_factor = float(inflation_factor)
                gap_close = int(gap_close)
                maximum_tree_density = float(maximum_tree_density)
                visualise = False if visualise == "False" else True
                show_images = False if show_images == "False" else True
                return binary_image, blur_size, binarization_threshold, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, convexity_min, min_size_factor, inflation_factor, gap_close, maximum_tree_density, visualise, show_images

    binary_image, blur_size, binarization_threshold, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, convexity_min, min_size_factor, inflation_factor, gap_close, maximum_tree_density, visualise, show_images = cast_params(binary_image, blur_size, binarization_threshold, MAX_ROAD_WIDTH, MIN_ROAD_WIDTH, convexity_min, min_size_factor, inflation_factor, gap_close, maximum_tree_density, visualise, show_images)
    
    # Open the geotiff using rasterio
    with rasterio.open(map_directory + 'geo.tiff') as raster:
        raster_image = raster.read()
    modern_roads = transform_linestrings(map_directory, raster.transform)
    
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
    base64_images.append({"label": "Thresholded map image", "image": base64.b64encode(cv2.imencode('.png', binary_image)[1]).decode("utf-8")})      
     
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
    print("... Done.")
    
    base64_images.append({"label": "Thinned map image", "image": base64.b64encode(cv2.imencode('.png', binary_image)[1]).decode("utf-8")})
    
    likely_roads = []
    for i, contour in enumerate(contours):
        # print("{}/{}".format(i+1, len(contours)))
        
        if not contour_validity[i]:
            continue # Reject contour
        
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        if hull_area == 0:
            continue # Reject contour
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
        
        if templating: # (Woodland templates rather than road templates)
            
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
        
        visualisation_contoursets["likely_road_shape"][2].append(contour)# Red for likely road  
                    
        likely_roads.append(emmentaler_eroded)
            
    print(str(len(likely_roads)) + ' likely roads found.')
    
    likely_roads = sum(likely_roads)
    
    # ## Next, dilate/erode to close any *small* gaps in road sections
    # print("Dilating ...")
    # kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gap_close, gap_close))
    # likely_roads = cv2.dilate(likely_roads, kernel, iterations=1)        
    
    ## Skeletonize
    print("Skeletonizing ...")
    skeleton = skeletonize(likely_roads / 255.).astype(np.uint8) * 255
    base64_images.append({"label": "Skeletonized likely roads", "image": base64.b64encode(cv2.imencode('.png', skeleton)[1]).decode("utf-8")}) 
    
#######################
## VECTOR PROCESSING ##
#######################
    
    ## Divide contours (which are coincident loops) into single lines, starting a new line at each junction
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
                contour_list.insert(0, contour[i+1:])
                break
        if not divide and len(contour) > 1:
            split_contours.append(contour)
    
    lineStrings = []
    for split_contour in split_contours:
        lineStrings.append(geometry.LineString(np.array(split_contour).reshape(-1, 2)).simplify(2))
    
    ## Now create new LineStrings to patch short gaps between potential road lines
    used_endpoints = set()
    disjointed = set()
    
    for i, line in enumerate(lineStrings):
        for point in [line.coords[0], line.coords[-1]]:
            if point in used_endpoints:
                continue
            used_endpoints.add(Point(point))
            shared = False
            for k, other in enumerate(lineStrings):
                if i == k:
                    continue
                if point in [other.coords[0], other.coords[-1]]:
                    shared = True
                    break
            if not shared:
                disjointed.add(Point(point))
                break  

    for point1, point2 in combinations(used_endpoints, 2):
        if (point1 in disjointed or point2 in disjointed) and point1.distance(point2) <= gap_close:
            lineStrings.append(LineString([point1, point2]))
    
    ## Test the proximity of likely road edges at sample points along each lineString
    proximity_visualisation = cv2.cvtColor(binary_image, cv2.COLOR_GRAY2BGR)
    proximity_visualisation = draw_linestrings_on_image(proximity_visualisation, modern_roads, linestring_color = (0, 255, 255), linestring_thickness = 3)
    probable_roads = []
    improbable_roads = []
    for lineString in lineStrings:
        testLength = lineString.length - MAX_ROAD_WIDTH # Do not test in proximity to junctions
        if testLength <= 0:
            improbable_roads.append(lineString)
            continue
        previousTest = None
        residual = lineString
        test_point_count = max(2, 1 + math.ceil(testLength / MAX_ROAD_WIDTH)) #  Test at least every MAX_ROAD_WIDTH pixels
        interval_length = testLength / (test_point_count - 1)
        previouspoint = lineString.interpolate(MAX_ROAD_WIDTH / 4)
        # Iterate over the intervals and find the normal_vector at each one
        for i in range(test_point_count):
            test_distance = MAX_ROAD_WIDTH / 2 + interval_length * i
            test_point = lineString.interpolate(test_distance)
            cv2.circle(proximity_visualisation, (int(test_point.x), int(test_point.y)), 4, (0, 0, 255), -1)
            normal_angle = np.pi/2 + np.arctan2(test_point.y - previouspoint.y, test_point.x - previouspoint.x)
            normal_vector = np.array([-np.cos(normal_angle), np.sin(normal_angle)])
    
            # Test the binary image at points along the normal vector
            likely_road = 0
            for sign in [-1, 1]:
                for d in range(math.ceil(MAX_ROAD_WIDTH / 2)):
                    offset_pixel = (int(round(test_point.x + sign * d * normal_vector[0])), int(round(test_point.y - sign * d * normal_vector[1])))
                    cv2.circle(proximity_visualisation, (int(offset_pixel[0]), int(offset_pixel[1])), 2, (0, 255, 0), -1)
                    if offset_pixel[0] >= 0 and offset_pixel[0] < binary_image.shape[1] and offset_pixel[1] >= 0 and offset_pixel[1] < binary_image.shape[0] and binary_image[offset_pixel[1],offset_pixel[0]] == 0:
                        likely_road += 1
                        break
            likely_road = likely_road == 2 # Must find road line on both sides
            if i > 0:
                if previousTest != likely_road:
                    split_residual = split(residual, test_point)
                    residual = split_residual.geoms[-1]
                    if previousTest:
                        probable_roads.append(split_residual.geoms[0])
                    else:
                        improbable_roads.append(split_residual.geoms[0])
            previousTest = likely_road
            previouspoint = test_point
        if previousTest:
            probable_roads.append(residual)
        else:
            improbable_roads.append(residual)
            
    base64_images.append({"label": "Road boundary checks (with modern OS roads)", "image": base64.b64encode(cv2.imencode('.png', proximity_visualisation)[1]).decode("utf-8")})
    
    # Reproject LineStrings to original raster CRS
    probable_roads_transformed, improbable_roads_transformed = [[transform(lambda x, y: rasterio.transform.xy(raster.transform, y, x), linestring) for linestring in linestrings] for linestrings in [probable_roads, improbable_roads]]
    gdf = gpd.GeoDataFrame(geometry=[MultiLineString(probable_roads_transformed), MultiLineString(improbable_roads_transformed)])
    gdf['name'] = ['probable_roads', 'improbable_roads']
    gdf.crs = "EPSG:4326"
    vector_json = {"gpkg": gdf.to_json()}
     
###################
## VISUALISATION ##
###################
    
    if visualise:
        
        visualisation = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2BGRA)
        for _, visualisation_contourset in visualisation_contoursets.items():
            overlay = np.zeros((height, width, 4), dtype=np.uint8)
            shape = overlay.copy()
            cv2.drawContours(shape, visualisation_contourset[2], -1, (255,255,255,255), -1) # Create mask for shading
            overlay[:] = np.concatenate([np.array(visualisation_contourset[0], dtype=np.uint8), [255]]) # Add colour
            shaded = cv2.addWeighted(overlay, visualisation_contourset[1], visualisation, 1 - visualisation_contourset[1], 0) # Set opacity
            visualisation = np.where(shape == 255, shaded, visualisation) # Draw shading
            cv2.drawContours(visualisation, visualisation_contourset[2], -1, visualisation_contourset[0], visualisation_contourset[3]) # Draw outlines
        
        for improbable_road in improbable_roads:
            coords = np.array(improbable_road.coords, np.int32)
            coords = coords.reshape(-1, 1, 2)
            cv2.polylines(visualisation, [coords], isClosed=False, color=(255, 0, 0, 255), thickness=1)
        for probable_road in probable_roads:
            coords = np.array(probable_road.coords, np.int32)
            coords = coords.reshape(-1, 1, 2)
            cv2.polylines(visualisation, [coords], isClosed=False, color=(0, 255, 255, 255), thickness=2)
    
        base64_images.append({"label": "Segmented map image", "image": base64.b64encode(cv2.imencode('.png', visualisation)[1]).decode("utf-8")}) 
        
        if show_images:
            cv2.imshow("Binary Image", binary_image)
            cv2.imshow('skeleton', skeleton) 
            cv2.imshow('proximity_visualisation', proximity_visualisation) 
            cv2.imshow('likely_roads', visualisation) 
            cv2.waitKey(0)
    
    return contours, skeleton, base64_images, vector_json