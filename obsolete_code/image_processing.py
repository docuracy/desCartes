'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''
import cv2
import math
import numpy as np
from skimage.morphology import skeletonize
import os
import geopandas as gpd
from shapely.geometry import Point, LineString

# Attempt to bridge gaps in skeleton by dilation and re-skeletonization
def skeleton_contours(skeleton_binary, raster_image_gray, gap = 15, step = 1, SHOW_IMAGES = False, OUTPUTDIR = False): # Larger steps run risk of blurring
    print('Skeletonize the binary image and find contours ...')    
    def skeleton_uint8(img):
        img = img > 0
        img = skeletonize(img)
        return (img * 255).astype(np.uint8)
    skeleton = skeleton_uint8(skeleton_binary)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (step,step))
    for gap_count in range(0, gap, step):
        skeleton_binary = cv2.dilate(skeleton, kernel, iterations=1)
        skeleton = skeleton_uint8(skeleton_binary)
    contours = cv2.findContours(skeleton, cv2.RETR_LIST , cv2.CHAIN_APPROX_NONE)[0]
    print('... done.')    
    if SHOW_IMAGES:
        raster_image_contours = cv2.cvtColor(raster_image_gray, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(raster_image_contours, contours, -1, (0,0,255), 3)
        cv2.imshow("Image with Contours", raster_image_contours)
        cv2.imwrite(os.path.join(OUTPUTDIR, 'Image with contours.png'), raster_image_contours)
        cv2.waitKey(0)
    return contours

def erase_matches(gray_image, binary_image, template_dir, template_filename, threshold=0.7, rotation_step = 0, SHOW_IMAGES = False, OUTPUTDIR = False):
    template = cv2.imread(f"{template_dir}/{template_filename}", 0)
    binarized_template = cv2.threshold(template, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    rows, cols = binarized_template.shape
    border = cv2.copyMakeBorder(binarized_template, rows, rows, cols, cols, cv2.BORDER_CONSTANT, value=255)
    
    found_matches = []

    for angle in range(0, 10 if rotation_step == 0 else 360, 100 if rotation_step == 0 else rotation_step):
        # Rotate the template image
        rows, cols = template.shape
        M = cv2.getRotationMatrix2D((cols + cols, rows + rows), angle, 1)
        rotated_template = cv2.warpAffine(border, M, (cols + cols * 2, rows + rows * 2))
        cropped_template = rotated_template[rows:rows + rows, cols:cols + cols]
        res = cv2.matchTemplate(gray_image, cropped_template, cv2.TM_CCOEFF_NORMED)
        # Perform template matching
        if SHOW_IMAGES:
            cv2.imshow(f'Rotated template: {template_filename} - {angle}', rotated_template)
        loc = np.where(res >= threshold)
        found_matches.extend(list(zip(*loc[::-1])))
        
    print(f'{len(found_matches)} {template_filename} matches found.')
    for pt in found_matches:
        for i in range(cropped_template.shape[0]):
            for j in range(cropped_template.shape[1]):
                if cropped_template[i][j] == 0:
                    binary_image[pt[1]+i][pt[0]+j] = 255

    gray_image_outlined = cv2.cvtColor(gray_image, cv2.COLOR_GRAY2BGR)
    for pt in found_matches:
        top_left = (pt[0], pt[1])
        bottom_right = (pt[0] + cropped_template.shape[1], pt[1] + cropped_template.shape[0])
        cv2.rectangle(gray_image_outlined, top_left, bottom_right, (0,0,255), 2)
    if SHOW_IMAGES:
        cv2.imshow(f'Match locations: {template_filename}', gray_image_outlined)
        cv2.imwrite(os.path.join(OUTPUTDIR, f'Match locations - {template_filename}.png'), gray_image_outlined)
        cv2.waitKey(0)

    return binary_image, gray_image_outlined

def template_density(contour, templates, thresholds, gray_image):
    print('Checking template density...')
    mask = np.zeros_like(gray_image)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    masked_image = cv2.bitwise_and(gray_image, mask)
    
    total_template_area = 0
    for i, template in enumerate(templates):
        res = cv2.matchTemplate(masked_image, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= thresholds[i])
        total_template_area += len(loc[0]) * template.shape[0] * template.shape[1]
    
    print('... done.')
    return total_template_area / cv2.contourArea(contour)

def erase_areas(image, 
                raster_image_gray,
                factor, 
                closed = False, 
                black = False, 
                circles = False, 
                blobs = False, 
                contours = True, 
                dashes = False,
                subtract = False,
                aspect_ratio_max = .15,
                contour_area_min = False,
                contour_width_max = False,
                convexity_min = .4,
                shading = False,
                template_dir = './data/templates',
                template_filenames = False,
                thresholds = False,
                template_density_threshold = .4,
                SHOW_IMAGES = False,
                MIN_ROAD_WIDTH = 3,
                MAX_ROAD_WIDTH = 15,
                window = -1,
                OUTPUTDIR = False
                ):
    if contour_area_min == False:
        contour_area_min = 2 * MIN_ROAD_WIDTH * MAX_ROAD_WIDTH
    if contour_width_max == False:
        contour_width_max = 3 * MAX_ROAD_WIDTH
    colour = 'black' if black else 'white'
    shading = 1 if False else -1
    form = 'shapes' if contours else 'areas'
    erasure = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    image = cv2.bitwise_not(image) if (black and not circles and not blobs) else image
    size = factor * (MIN_ROAD_WIDTH ** 2) if (contours and not circles and not blobs) else int(factor)
    if template_filenames:
        templates = []
        for i, template_filename in enumerate(template_filenames):
            templates.append(cv2.imread(f"{template_dir}/{template_filename}", 0))
        
    if circles: # Used for removing, for example, dot shading (not very effective!)
        form = 'circles'
        r = factor
        size = (2*r+4, 2*r+4)
        template = np.ones(size, dtype=np.uint8)
        cv2.circle(template, (r+2,r+2), r, (0,0,0), -1)
        res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        # Threshold the result to find the locations where the image matches the kernel
        loc = np.where(res >= 0.6)
        # Draw circles of 8px diameter at the matching locations
        for pt in zip(*loc[::-1]):
            cv2.circle(image, (pt[0] + r+2, pt[1] + r+2), r, (255, 255, 255), -1)   
            cv2.circle(erasure, (pt[0] + r+2, pt[1] + r+2), r, (0, 0, 255, 128), shading)   
    elif blobs:
        form = 'blobs'
        params = cv2.SimpleBlobDetector_Params()
        params.filterByColor =True
        params.blobColor = 0 if black == True else 1
        params.filterByCircularity = True
        params.maxCircularity = 1
        params.filterByArea = True
        params.maxArea = size
        detector = cv2.SimpleBlobDetector_create(params)
        keypoints = detector.detect(image)
        for kp in keypoints:
            x, y = int(kp.pt[0]), int(kp.pt[1])
            r = int(kp.size / 2)
            cv2.circle(image, (x, y), r, (255, 255, 255), -1)
            cv2.circle(erasure, (x, y), r, (0, 0, 255, 128), shading)                    
    elif contours:
        contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if shading:
            contours = sorted(contours, key=cv2.contourArea, reverse=True)
        for contour in contours: 
            # Calculate areas of contour and its convex hull
            contour_area = cv2.contourArea(contour)
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            if hull_area == 0 or contour_area == 0:
                cv2.drawContours(erasure, [contour], -1, (0, 255, 255, 128), shading)
                continue # Reject contour
            convexity = contour_area / hull_area

            # Calculate aspect ratio
            width, height = cv2.minAreaRect(contour)[1]
            if width == 0 or height == 0:
                cv2.drawContours(erasure, [contour], -1, (0, 255, 255, 128), shading)
                continue # Reject contour
            else:
                aspect_ratio = min(width, height) / max(width, height)

            if aspect_ratio <= aspect_ratio_max and contour_area >= contour_area_min and min(width, height) <= contour_width_max:
                cv2.drawContours(erasure, [contour], -1, (0, 255, 0, 128), shading) # Try not to erase road sections
            elif convexity >= convexity_min or closed == False: 
                cv2.drawContours(image, [contour], 0, (0, 0, 0), -1)
                cv2.drawContours(erasure, [contour], -1, (255, 255, 0, 128), shading)
            else:
                # Find template density (can be used, for example, for detecting woodland) - RATHER SLOW
                templated = 0
                if template_filenames and contour_area >= contour_area_min:
                    templated = template_density(contour, templates, thresholds, raster_image_gray)
                    if templated > template_density_threshold:
                        print(templated)
                        cv2.drawContours(image, [contour], 0, (0, 0, 0), -1)
                        cv2.drawContours(erasure, [contour], -1, (0, 127, 255, 128), shading) # Orange
                if templated <= template_density_threshold:
                    cv2.drawContours(erasure, [contour], -1, (0, 0, 255, 128), shading)
    elif dashes:
        contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours: 
            # Define acceptable range of values for each metric
            std_deviation_multiplier = 3
            area_range = (25.34 - std_deviation_multiplier * 4.98, 25.34 + std_deviation_multiplier * 4.98)
            convexity_range = (0.9572 - std_deviation_multiplier * 0.0306, 0.9572 + std_deviation_multiplier * 0.0306)
            aspect_ratio_range = (0.5085 - std_deviation_multiplier * 0.1082, 0.5085 + std_deviation_multiplier * 0.1082)
            
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
            width, height = rect[1]
            if width == 0 or height == 0:
                continue # Reject contour
            else:
                aspect_ratio = min(width, height) / max(width, height)
                
            if not aspect_ratio_range[0] <= aspect_ratio <= aspect_ratio_range[1]:
                continue
            
            cv2.drawContours(erasure, [contour], -1, (0, 255, 0, 128), shading)
            
            ## TO DO: Draw dash contours in white on black, dilate to merge dashes and parallel lines,
            ## skeletonize and then get contours, and reduce those to single linestrings (as in desCartes.py).
            ## Get single-dash lines by eroding the dilated image until they disappear, then subtract from the dilated image;
            ## skeletonize and contour as before.
            ##
            ## The rest of this section is redundant except possibly for visualisation purposes.
            
            # angle = rect[2] # Rather imprecise
            
            # Calculate ellipse from contour
            ellipse = cv2.fitEllipse(contour)
            
            # Get ellipse parameters
            center, axes, angle = ellipse
            cx, cy = center[0], center[1]
            
            line_angle = (90 if axes[1] > axes[0] else 0) - angle
            line_angle = abs(line_angle % 360) % 180 # Normalise to range 0-180 degrees
            # Draw line
            line_length = int(max(width, height) * 3.5)
            line_start = (int(cx - line_length/2 * np.cos(np.deg2rad(line_angle))), int(cy + line_length/2 * np.sin(np.deg2rad(line_angle))))
            line_end = (int(cx + line_length/2 * np.cos(np.deg2rad(line_angle))), int(cy - line_length/2 * np.sin(np.deg2rad(line_angle))))
            cv2.line(erasure, line_start, line_end, (0, 0, 255, 128), thickness=1)
            
            
        '''
        print('area',mean_area,std_area)
        print('convexity',mean_convexity,std_convexity)
        print('aspect_ratio',mean_aspect_ratio,std_aspect_ratio)
            
        # area 25.346801346801346 4.982724181977989
        # convexity 0.957281371092532 0.03064098034608555
        # aspect_ratio 0.5085408549728891 0.1082271280592799
        '''

            
    else:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        mask = image
        eroded_image = cv2.erode(image, kernel, iterations=1)
        dilated_image = cv2.dilate(eroded_image, kernel, iterations=1)
        image = cv2.subtract(image, dilated_image) if subtract else dilated_image
        mask = mask != image
        erasure[mask] = [0, 0, 255, 255]
    image = cv2.bitwise_not(image) if (black and not circles and not blobs) else image
    message = 'Removed ' + colour + ' ' + form + ' (size ' + str(size) + ')'
    print(message)

    if SHOW_IMAGES:
        cv2.imshow(message + ' [' + str(window) + ']', erasure)
        cv2.imwrite(os.path.join(OUTPUTDIR, message + ' ' + str(window) + '.png'), erasure)
        cv2.waitKey(0)
        window += 1

    return image, erasure