'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''
import cv2
import numpy as np
from skimage.morphology import skeletonize
import os
import sys
import ast
import geopandas as gpd
from shapely.geometry import MultiPoint, Point, LineString
from utilities import unit_vector
from desCartes import vector_skeleton, cut, result_image, XY_to_EPSG4326

def snap_endpoints(gdf, tolerance):
    endpoints, _, _, endpoint_dictionary = endpoint_connectivity(gdf, full_dictionary = True)
    
    endpoint_lists = []
    visited_endpoints = set()
    for endpoint in endpoints:
        if endpoint in visited_endpoints:
            continue
        nearby_endpoints = []
        for other_endpoint in endpoints:
            if endpoint == other_endpoint:
                continue
            dist = Point(endpoint).distance(Point(other_endpoint))
            if dist <= tolerance:
                nearby_endpoints.append(other_endpoint)
                visited_endpoints.add(other_endpoint)
        endpoint_lists.append((endpoint, nearby_endpoints))
        
    for endpoint, nearby_endpoints in endpoint_lists:
        for nearby_endpoint in nearby_endpoints:
            nearby_lines = endpoint_dictionary[tuple(nearby_endpoint)]
            for nearby_line, polarity in nearby_lines:
                print(f'... snapping {nearby_line}: {nearby_endpoint} to {endpoint} ...')
                line = gdf.at[nearby_line, 'geometry']
                if polarity == 0:
                    coords = [(endpoint[0], endpoint[1])] + line.coords[1:]
                else:
                    coords = line.coords[:-1] + [(endpoint[0], endpoint[1])]
                gdf.at[nearby_line, 'geometry'] = LineString(coords)

    return gdf

def endpoint_connectivity(gdf, shape = False, margin = 5, full_dictionary = False):
    endpoints = set()
    connected_endpoints = set()
    endpoint_dictionary = {}
    for i, lineString in gdf.iterrows():
        for j, endpoint in enumerate([lineString.geometry.coords[0], lineString.geometry.coords[-1]]):
            if not shape == False:
                x, y = endpoint
                if x < margin or x > shape[1] - margin - 1 or y < margin or y > shape[0] - margin - 1:
                    print(f'Endpoint {endpoint} is near the edge of the image - ignoring.')
                    continue  # Endpoint is on the boundary of the image, skip it
            if endpoint not in endpoints:
                endpoints.add(endpoint)
                if full_dictionary == False:
                    endpoint_dictionary[tuple(endpoint)] = i, j
                else:
                    endpoint_dictionary[tuple(endpoint)] = [[i, j]]
            else:
                connected_endpoints.add(endpoint)
                if not full_dictionary == False:
                    endpoint_dictionary[tuple(endpoint)].append([i, j])
    unconnected_endpoints = endpoints - connected_endpoints
    # for endpoint in connected_endpoints:
    #     del endpoint_dictionary[tuple(endpoint)]
    return endpoints, connected_endpoints, unconnected_endpoints, endpoint_dictionary

def patch_vector_skeleton(gdf, image_shape, simplify = 1, tolerance = 10, discard = 3, discard_only = False, reskeletonize = False, visualise = True):
    
    # Find unconnected endpoints
    _, _, unconnected_endpoints, endpoint_dictionary = endpoint_connectivity(gdf, image_shape)
    
    # Skeletonization tends to leave short flicks at the ends of lines, so discard any short line end-sections, and update endpoint inventories
    endpoint_discards = []
    endpoint_adds = []
    for endpoint in unconnected_endpoints:
        line_idx, polarity = endpoint_dictionary[tuple(endpoint)]
        line = gdf.loc[line_idx, 'geometry'].simplify(simplify)
        if polarity == 1:
            line = line.reverse()
        coords = list(line.coords)
        changed = False
        while len(coords) > 2 and Point(coords[0]).distance(Point(coords[1])) < discard:
            if not changed:
                del endpoint_dictionary[tuple(coords[0])]
                endpoint_discards.append(coords[0])
            coords = coords[1:]
            changed = True
        if not changed:
            continue
        endpoint_dictionary[tuple(coords[0])] = line_idx, polarity
        endpoint_adds.append(coords[0])
        line = LineString(coords)
        if polarity ==1:
            line = line.reverse()
        gdf.loc[line_idx, 'geometry'] = line
    if discard_only == True:
        return gdf
    for endpoint in endpoint_discards:
        unconnected_endpoints.discard(endpoint)
    for endpoint in endpoint_adds:
        unconnected_endpoints.add(endpoint)
    
    # Calculate and store unit vector for extending each unconnected endpoint
    for endpoint in unconnected_endpoints:
        line_idx, polarity = endpoint_dictionary[tuple(endpoint)]
        line = gdf.loc[line_idx, 'geometry']
        if polarity == 1:
            line = line.reverse().simplify(2) # Without simplification, unit vector tends to direct only to adjacent pixels
        coords = list(line.coords)
        endpoint_dictionary[tuple(endpoint)] = line_idx, polarity, unit_vector(coords[0], coords[1]), 0, False, set() # Add 3 parameters at the end for step management    
        
    # Initialise test image
    patched_image = np.zeros((image_shape[0], image_shape[1]), dtype=np.uint8)
    for line in gdf.geometry:
        coords = np.array(line.coords)
        coords = np.round(coords).astype(int)
        cv2.polylines(patched_image, [coords], isClosed=False, color=255, thickness=1)
    test_image = patched_image.copy()
    if visualise:
        cv2.imshow('trimmed_linestrings', test_image)
        # cv2.waitKey(0)
    
    # Loop up to gap_close, extending each unconnected endpoint and drawing on test image until connection is made, then record loop value
    split_points = set()
    for step in range(1, tolerance + 1, 1):
        for endpoint in unconnected_endpoints:
            line_idx, polarity, extension_vector, step_extension, started, tested = endpoint_dictionary[tuple(endpoint)]
            if step == tolerance: # On final pass through the loop, update gdf and draw patched image using detected extension points
                step_point = (int(endpoint[0] - step_extension * extension_vector[0]), int(endpoint[1] - step_extension * extension_vector[1]))
                split_points.add((step_point, line_idx))
                line = gdf.loc[line_idx, 'geometry']
                if polarity == 1:
                    line = line.reverse()
                coords = list(line.coords)
                line = LineString([Point(step_point)] + coords[1:])
                if polarity == 1:
                    line = line.reverse()
                gdf.loc[line_idx, 'geometry'] = line
                if visualise:
                    pts = np.array([list(step_point), list(endpoint)], np.int32)
                    cv2.polylines(patched_image, [pts], isClosed=False, color=255, thickness=1)
            else:
                if step_extension == 0:
                    line = gdf.loc[line_idx, 'geometry']
                    if polarity == 1:
                        line = line.reverse()
                    coords = list(line.coords)
                    step_point = (int(coords[0][0] - step * extension_vector[0]), int(coords[0][1] - step * extension_vector[1]))
                    if step_point in tested: # Avoid retesting a now-painted pixel
                        continue
                    tested.add(step_point)
                    if (0 <= step_point[0] < image_shape[1]) and (0 <= step_point[1] < image_shape[0]):
                        if test_image[step_point[1], step_point[0]] == 0: # Must first pass at least one black pixel
                            endpoint_dictionary[tuple(endpoint)] = line_idx, polarity, extension_vector, 0, True, tested
                        elif started == True:
                            endpoint_dictionary[tuple(endpoint)] = line_idx, polarity, extension_vector, step, True, tested
                            print(f'{line_idx}: Found white pixel at {step_point} after {step} steps along {extension_vector} (polarity={polarity}) from {tuple(endpoint)}.')
                        pts = np.array([list(step_point), list(coords[0])], np.int32)
                        cv2.polylines(test_image, [pts], isClosed=False, color=255, thickness=1)
    
    if reskeletonize:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        patched_image = cv2.dilate(patched_image, kernel, iterations=1)
        skeleton = (skeletonize(patched_image > 0) * 255).astype(np.uint8)
        lineStrings = vector_skeleton(skeleton, simplify = 2, discard_length = False, discard_max_points = 2)
        gdf = gpd.GeoDataFrame(geometry = lineStrings)
        _, _, unconnected_endpoints, _ = endpoint_connectivity(gdf, image_shape)
        rows_to_drop = []
        for index, row in gdf.iterrows():
            if (row.geometry.coords[0] in unconnected_endpoints or row.geometry.coords[-1] in unconnected_endpoints) and row.geometry.length < 10:
                rows_to_drop.append(index)
        gdf = gdf.drop(rows_to_drop)
    elif len(split_points) > 0: # No use doing this if reskeletonizing
        print('Processing split_points ...')
        gdf_sindex = gdf.sindex
        for split_point, join_line_idx in split_points:
            matches_index = list(gdf_sindex.intersection(endpoint.buffer(3).bounds))
            matches_index = [idx for idx in matches_index if idx != join_line_idx]
            matches = gdf.iloc[matches_index]
            for i, match in matches.iterrows():
                if split_point.distance(match.geometry) <= tolerance:
                    # Divide the linestring at the closest point to split_point
                    first_half, second_half = cut(match.geometry, match.geometry.project(Point(split_point)))
                    if second_half == False:
                        continue
            
                    print(f'... dropping split linestring {i} ...')
                    # Create a new DataFrame with the first half of the line and its attributes
                    new_row1 = gpd.pd.DataFrame(gdf.loc[i])
                    new_row1['geometry'] = first_half
                    # Create a new DataFrame with the second half of the line and its attributes
                    new_row2 = gpd.pd.DataFrame(gdf.loc[i])
                    new_row2['geometry'] = second_half
                    # Concatenate the original DataFrame with the two new rows
                    gdf = gpd.pd.concat([gdf.drop(i), new_row1, new_row2], ignore_index=True)
                
    if visualise:
        cv2.imshow('Test Image', test_image)
        cv2.imshow('patched_image', patched_image)
        # cv2.waitKey(0)

    return gdf
        
def patch_gdf(gdf, image_shape = False, tolerance=20, snap_to_line = False): # If snap_to_line is True, linestrings with unconnected endpoints will be extended to meet the closest point on another linestring
    if tolerance == 0:
        return gdf
        
    _, _, unconnected_endpoints, endpoint_dictionary = endpoint_connectivity(gdf, image_shape)
    
    def lookup_lineString(endpoint, reverse): # reverse == True indicates that matching endpoint should be last point in returned lineString
        line_idx, polarity = endpoint_dictionary[tuple(endpoint.geometry.coords[0])]
        lineString = gdf.iloc[line_idx].geometry.simplify(2)
        polarity = polarity == 1 # True if matching endpoint is last point
        if reverse != polarity:
            lineString = lineString.reverse()
        return line_idx, polarity, lineString

    # Create spatial index of unconnected endpoints
    endpoint_gdf = gpd.GeoDataFrame.from_records([{'geometry': Point(endpoint)} for endpoint in unconnected_endpoints])
    endpoint_sindex = endpoint_gdf.sindex
    
    if snap_to_line:
        gdf_sindex = gdf.sindex
    
    connected = set() # indices of newly-connected endpoints
    drop = set()
    split_points = set() # collect lines that need to be split following a join with another line
    for i, endpoint in endpoint_gdf.iterrows():
        print(f'Examining {i} {endpoint.geometry} ...')
        
        if snap_to_line:
            line_idx, polarity, extend_line = lookup_lineString(endpoint, reverse = False)
            matches_index = list(gdf_sindex.intersection(endpoint.geometry.buffer(tolerance).bounds))
            matches_index = [idx for idx in matches_index if idx != line_idx]
            matches = gdf.iloc[matches_index]
            
            min_dist = np.inf
            closest_point = None
            
            # Get the unit vector between the first two points of extend_line
            vector = unit_vector(extend_line.coords[0], extend_line.coords[1])
        
            # Extend extend_line backwards by a distance of tolerance
            extended_coords = [(extend_line.coords[0][0] - vector[0]*tolerance, extend_line.coords[0][1] - vector[1]*tolerance), extend_line.coords[0]]
            extended_line = LineString(extended_coords)
            
            # Check for intersections before picking closest point
            for idx, line in matches.iterrows():
                if extended_line.intersects(line.geometry):
                    intersection = extended_line.intersection(line.geometry)
                    if isinstance(intersection, MultiPoint):
                        for point in intersection.geoms:
                            dist_to_point = endpoint.geometry.distance(point)
                            if dist_to_point < min_dist:
                                closest_point = point
                                closest_line = idx
                                min_dist = dist_to_point
                        if not closest_point is None:
                            print(f'... multiple intersections found, closest at {closest_point} ({min_dist}) ...')
                    elif isinstance(intersection, Point):
                        dist_to_point = endpoint.geometry.distance(closest_point)
                        if dist_to_point < min_dist:
                            closest_point = intersection
                            closest_line = idx
                            min_dist = dist_to_point
                            print(f'... single intersection via {extended_line} found at {closest_point} ({min_dist}) ...')
            
            # If no intersection found by extending the line, look for a nearby point
            if closest_point is None:
                print('... no intersection found, looking for nearby point ...')
                for idx, line in matches.iterrows():
                    dist_to_line = line.geometry.distance(endpoint.geometry)
                    if dist_to_line < min_dist:
                        closest_point = line.geometry.interpolate(line.geometry.project(endpoint.geometry))
                        closest_line = idx
                        min_dist = dist_to_line
                    
            if min_dist <= tolerance and closest_point is not None:
                print(f'... joined to {closest_point}.')
                split_points.add((closest_point.coords, closest_line))
                if polarity == 0:
                    gdf.loc[line_idx, 'geometry'] = LineString([closest_point.coords[0]] + list(gdf.iloc[line_idx].geometry.coords))
                else:
                    gdf.loc[line_idx, 'geometry'] = LineString(list(gdf.iloc[line_idx].geometry.coords) + [closest_point.coords[0]])
            else:
                print('... no close line found.')
            
        else:
            if i in connected:
                print(f'... {i} already connected ...')
                continue
            matches_index = list(endpoint_sindex.intersection(endpoint.geometry.buffer(tolerance).bounds))
            matches_index = [idx for idx in matches_index if idx != i and idx not in connected]  # Remove any previously dropped indices
            if len(matches_index) == 0:
                print(f'... no matches found for {i} ...')
                continue
            connected.add(i)
            connected.update(matches_index)
            matches = endpoint_gdf.iloc[matches_index]
            line_idx, _, line = lookup_lineString(endpoint, reverse = True)
            for j, (_, matched_point) in enumerate(matches.iterrows()):
                matched_line_idx, _, matched_line = lookup_lineString(matched_point, reverse = False)
                if line_idx == matched_line_idx:
                    continue                
                # Join the first match, link any subsequent matches
                if j == 0:
                    print(f'... merge {i} and {matches_index[j]} ...')
                    merged_lineString = LineString(list(line.coords) + list(matched_line.coords))
                else:
                    print(f'... link {i} to {matches_index[j]} ...')
                    merged_lineString = LineString([endpoint] + list(matched_line.coords))
                for j, endpoint in enumerate([merged_lineString.coords[0], merged_lineString.coords[-1]]):
                    endpoint_dictionary[tuple(endpoint)] = len(gdf), j # Update endpoint_dictionary with reference to new lineString
                drop.update([line_idx, matched_line_idx])
                gdf = gpd.pd.concat([gdf, gpd.GeoDataFrame(geometry=[merged_lineString])], ignore_index=True)
                
    if len(split_points) > 0:
        for split_point, line_idx in split_points:
            # Divide the linestring at the closest point to split_point
            first_half, second_half = cut(gdf.loc[line_idx].geometry, gdf.loc[line_idx].geometry.project(Point(split_point)))
            if second_half == False:
                continue
            
            print(f'... dropping split linestring {line_idx} {"again " if line_idx in drop else ""} ...')
            # Create a new DataFrame with the first half of the line and its attributes
            new_row1 = gpd.pd.DataFrame(gdf.loc[line_idx].drop('geometry')).T
            new_row1['geometry'] = first_half
            # Create a new DataFrame with the second half of the line and its attributes
            new_row2 = gpd.pd.DataFrame(gdf.loc[line_idx].drop('geometry')).T
            new_row2['geometry'] = second_half
            # Concatenate the original DataFrame with the two new rows
            gdf = gpd.pd.concat([gdf, new_row1, new_row2], ignore_index=True)
            drop.update([line_idx])
            
    gdf = gdf.drop(drop)
    gdf = gdf.reset_index(drop=True)
        
    return gdf

def coloured_roads(image, map_directory, transform, colours, visualise = False):
    
    scale = 4 # For scaling between different map tilesets, one at zoom=17, the other at zoom=15
    # scale = 1 # FOR TESTING ***************************
    
    result_images = []

    image = cv2.cvtColor(image.transpose(1, 2, 0), cv2.COLOR_RGB2BGR) # Convert from TIFF to BGR
    result_images.append(result_image(visualise, map_directory, "Original coloured image", image))
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB) # Convert image to LAB colour space
    mask_accumulator = np.zeros((lab.shape[0], lab.shape[1]), dtype=np.uint8)
    
    if visualise:
        cv2.imshow('image', image)
    
    # Create masks for visualization purposes
    mask_bgr = np.zeros((lab.shape[0], lab.shape[1], 3), dtype=np.uint8)
    vector_bgr = mask_bgr.copy()
    
    vectors = [] # Ready to collect records for GeoDataFrame
    
    for colour_info in colours:
        
        print(f'Processing {colour_info["name"]}')
        
        # Extract the mean and std deviation of the LAB values for the current colour
        mean_L, mean_a, mean_b = colour_info['lab_colour']['mean']
        std_L, std_a, std_b = colour_info['lab_colour']['std']
        
        # Create a mask of True values for pixels that are within the expected range for the current colour
        colour_mask = (lab[:, :, 0] >= mean_L * 255 - colour_info['lab_colour']['confidence'] * std_L * 255) & (lab[:, :, 0] <= mean_L * 255 + colour_info['lab_colour']['confidence'] * std_L * 255) \
                    & (lab[:, :, 1] >= mean_a * 255 - colour_info['lab_colour']['confidence'] * std_a * 255) & (lab[:, :, 1] <= mean_a * 255 + colour_info['lab_colour']['confidence'] * std_a * 255) \
                    & (lab[:, :, 2] >= mean_b * 255 - colour_info['lab_colour']['confidence'] * std_b * 255) & (lab[:, :, 2] <= mean_b * 255 + colour_info['lab_colour']['confidence'] * std_b * 255)
        
        mask_bgr[colour_mask] = colour_info['bgr_colour'] # Visualisation of extracted colours
        if visualise:
            cv2.imshow('mask_bgr', mask_bgr)
            
        closed_mask = np.where(colour_mask, 255, 0).astype(np.uint8)
        
        # Using contours, remove unwanted shapes
        if len(colour_info['shapes']) > 0:
            contours, _ = cv2.findContours(closed_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)    
            for shape in colour_info['shapes']:
                shape['area_range'] = [shape['area'] * (1-shape['tolerance']), shape['area'] * (1+shape['tolerance'])]
                shape['convexity_range'] = [shape['convexity'] * (1-shape['tolerance']), shape['convexity'] * (1+shape['tolerance'])]
                shape['aspect_ratio_range'] = [shape['aspect_ratio'] * (1-shape['tolerance']), shape['aspect_ratio'] * (1+shape['tolerance'])]
            for contour in contours: 
                # Calculate areas of contour and its convex hull
                contour_area = cv2.contourArea(contour)
                hull = cv2.convexHull(contour)
                hull_area = cv2.contourArea(hull)
                if hull_area == 0 or contour_area == 0:
                    continue # Reject contour
                convexity = contour_area / hull_area
    
                # Calculate aspect ratio
                width, height = cv2.minAreaRect(contour)[1]
                if width == 0 or height == 0:
                    continue # Reject contour
                else:
                    aspect_ratio = min(width, height) / max(width, height)
                    
                print(f'{contour_area} {convexity} {aspect_ratio}')
                    
                for shape in colour_info['shapes']:
                    print(f'Looking for {shape["type"]} {shape["area_range"]}...')
                    if shape['area_range'][0] < contour_area <  shape['area_range'][1] \
                            and shape['convexity_range'][0] < convexity <  shape['convexity_range'][1] \
                            and shape['aspect_ratio_range'][0] < aspect_ratio <  shape['aspect_ratio_range'][1]:
                        print(f'Shape found: {shape["type"]}')
                        cv2.drawContours(closed_mask, [contour], -1, 0, -1)
                        cv2.drawContours(mask_bgr, [contour], -1, (0, 0, 0), -1)
                        
        if colour_info['kernel']['close'] > 0:
            kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (colour_info['kernel']['close'], colour_info['kernel']['close']))
            closed_mask = cv2.morphologyEx(closed_mask, cv2.MORPH_CLOSE, kernel_close) # Try to close holes
            if visualise:
                cv2.imshow('closed_mask', closed_mask)
        if colour_info['kernel']['open'] > 0:
            kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (colour_info['kernel']['open'], colour_info['kernel']['open']))
            closed_mask = cv2.morphologyEx(closed_mask, cv2.MORPH_OPEN, kernel_open) # Try to remove thin lines (including contours in the case of buff lines
            if visualise:
                cv2.imshow('opened_mask', closed_mask)
        if colour_info['kernel']['reclose'] > 0:
            kernel_reclose = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (colour_info['kernel']['reclose'], colour_info['kernel']['reclose']))
            closed_mask = cv2.morphologyEx(closed_mask, cv2.MORPH_CLOSE, kernel_reclose) # Try to close holes
            if visualise:
                cv2.imshow('re-closed_mask', closed_mask)
        
        # Exclude previously selected pixels (red lines may have edges interpreted as brown)
        closed_mask = np.where(mask_accumulator, 0, closed_mask).astype(np.uint8)
        mask_accumulator = np.where(closed_mask, 255, mask_accumulator).astype(np.uint8)
        
        skeleton = (skeletonize(closed_mask > 0) * 255).astype(np.uint8)
        if visualise:
            cv2.imshow('skeleton_1', skeleton)
            
        lineStrings = vector_skeleton(skeleton, simplify = 0, discard_length = 10, discard_max_points = 2)
        
        if visualise:  
            skeleton_2 = np.zeros((lab.shape[0], lab.shape[1]), dtype=np.uint8)
            for lineString in lineStrings:
                coords = np.array(lineString.coords)
                coords = coords.astype(np.int32).reshape(-1, 1, 2)
                cv2.polylines(skeleton_2, [coords], isClosed=False, color=255, thickness=1)
            cv2.imshow('vector_skeleton', skeleton_2)
        
        linestring_gdf = gpd.GeoDataFrame(geometry = lineStrings)
        # linestring_gdf = patch_vector_skeleton(linestring_gdf, image.shape, simplify = 1, discard = 10, tolerance = colour_info['gap_close'], reskeletonize = True)        
        # linestring_gdf = patch_gdf(linestring_gdf, tolerance = colour_info['gap_close'])
        
        if visualise:  
            for _, lineString in linestring_gdf.iterrows():
                coords = np.array(lineString.geometry.coords)
                coords = coords.astype(np.int32).reshape(-1, 1, 2)
                cv2.polylines(vector_bgr, [coords], isClosed=False, color=colour_info['bgr_colour'], thickness=1)
            cv2.imshow('vector_bgr', vector_bgr)
        
        # print(unconnected_endpoints)
        # cv2.waitKey(0)
        # sys.exit()
            
        for _, lineString in linestring_gdf.iterrows():    
            vectors.append({'label': colour_info['label'], 'colour': str(colour_info['bgr_colour']), 'geometry': lineString.geometry}) 
    
    result_images.append(result_image(visualise, map_directory, "Extracted colours", mask_bgr))
    result_images.append(result_image(visualise, map_directory, "Extracted roads", vector_bgr))
    roads = gpd.GeoDataFrame.from_records(vectors)
    roads = snap_endpoints(roads, 10)
    roads = patch_vector_skeleton(roads, image.shape, simplify = 1, discard = 8, discard_only = True, tolerance = 30, reskeletonize = False)
    roads = patch_gdf(roads, image_shape = image.shape, tolerance = 100, snap_to_line = True)
    roads = snap_endpoints(roads, 10)
        
    coloured_roads_EPSG4326_gdf = XY_to_EPSG4326(roads, transform)
    coloured_roads_EPSG4326_gdf.to_file(map_directory + 'desCartes.gpkg', layer="coloured_roads", driver="GPKG")
    
    if visualise:
        final_bgr = np.zeros((lab.shape[0], lab.shape[1], 3), dtype=np.uint8)
        for _, lineString in roads.iterrows():
            coords = np.array(lineString.geometry.coords)
            coords = coords.astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(final_bgr, [coords], isClosed=False, color=ast.literal_eval(lineString.colour), thickness=2)
            
        cv2.imshow('mask_bgr', mask_bgr)
        cv2.imshow('final_bgr', final_bgr)
        cv2.waitKey(0)
        result_images.append(result_image(visualise, map_directory, "Patched roads", final_bgr))
    
    # Scale x4 to account for different zoom levels of OS map series
    roads = gpd.GeoDataFrame.from_records([{ \
            'label': colour_info['label'], \
            'colour': colour_info['bgr_colour'], \
            'geometry': LineString([(scale*x, scale*y) for x, y in zip(lineString.geometry.xy[0], lineString.geometry.xy[1])])} for _, lineString in roads.iterrows()])
            
    return roads, False, result_images, ''