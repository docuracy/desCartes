'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''

import cv2
import numpy as np
from skimage.morphology import skeletonize
import base64

def road_contours(grayscale_image, 
                  binary_image = False, 
                  blur_size = 3, # Used to try to remove blemishes from image - greatly reduces number of spurious contours and consequent processing-time
                  binarization_threshold = 210,
                  MAX_ROAD_WIDTH = 14, 
                  MIN_ROAD_WIDTH = 6, 
                  convexity_min = .9, 
                  min_size_factor = 10, # Multiplied by int(MAX_ROAD_WIDTH)^2 to give minimum size for a contour to be considered
                  inflation_factor = 2.3, # Multiplied by int(MAX_ROAD_WIDTH) to limit average breadth of a contour perpendicular to its skeleton
                  gap_close = 3, # For closing gaps between likely roads
                  templating = True,
                  template_dir = './data/templates', 
                  template_filenames = ['tree-broadleaf.png', 'tree-conifer.png'], 
                  thresholds = [.7, .7],
                  maximum_tree_density = .1,
                  visualise = True,
                  show_images = False
                  ):
    
    # Initialise visualisation arrays
    visualisation_contoursets = {
        "size": [(127,127,127),.5,[],1], # GREY
        "convexity": [(0,255,0),.3,[],2], # GREEN
        "under-inflation": [(255,0,255),.3,[],2], # PURPLE
        "over-inflation": [(255,255,0),.6,[],2], # TEAL
        "woodland": [(0,255,255),.3,[],2], # YELLOW
        "likely_road_shape": [(0,0,255),.5,[],2], # RED
        "likely_road_line": [(255,0,0),.9,[],2] # BLUE
        } 
    
    print('Finding road contours ...')
    MIN_SIZE = float(min_size_factor) * int(MAX_ROAD_WIDTH) ** 2
    if binary_image is False:
        blurred_grayscale_image = cv2.medianBlur(grayscale_image, int(blur_size)) 
        # binary_image = cv2.threshold(grayscale_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1] # Tends to create gaps in road lines
        _, binary_image = cv2.threshold(blurred_grayscale_image, int(binarization_threshold), 255, cv2.THRESH_BINARY)
    height, width = binary_image.shape[:2]

    base64_images = []
    base64_images.append({"label": "Thresholded map image", "image": base64.b64encode(cv2.imencode('.png', binary_image)[1]).decode("utf-8")})      
     
    # Thin all black lines to 1px
    binary_image = np.invert(binary_image)  
    binary_image = skeletonize(binary_image / 255).astype(np.uint8) * 255
    # Dilate to close small gaps in road outlines    
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(MIN_ROAD_WIDTH), int(MIN_ROAD_WIDTH)))
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
        if convexity > float(convexity_min):
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
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(MAX_ROAD_WIDTH * float(inflation_factor)), int(MAX_ROAD_WIDTH * float(inflation_factor))))
        emmentaler_eroded = cv2.erode(emmentaler, kernel, iterations=1)
        emmentaler_eroded = np.where(emmentaler_eroded == 0, emmentaler, 0)
        
        emmentaler_contours = cv2.findContours(emmentaler_eroded, cv2.RETR_EXTERNAL , cv2.CHAIN_APPROX_NONE)[0]
        
        double_roadwidth = (MAX_ROAD_WIDTH + MIN_ROAD_WIDTH)
        expected_road_perimeter = double_roadwidth + (4 * contour_areas[i] / double_roadwidth)
        # inflation = cv2.arcLength(contour, True) * double_roadwidth / expected_road_perimeter
        inflation = cv2.arcLength(emmentaler_contours[0], True) * double_roadwidth / expected_road_perimeter
        print(inflation, double_roadwidth / float(inflation_factor))
        if inflation < double_roadwidth / float(inflation_factor):
            visualisation_contoursets["under-inflation"][2].append(contour) # Purple for under-inflation rejection
            continue # Reject contour
        elif inflation > double_roadwidth * float(inflation_factor):
            visualisation_contoursets["over-inflation"][2].append(contour) # Teal for over-inflation rejection
            continue # Reject contour        
        
        if bool(templating):
            
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
            if match_count * template_area / emmentaler_area > float(maximum_tree_density):
                visualisation_contoursets["woodland"][2].append(contour) # Yellow for tree density rejection
                continue # Reject contour    
        
        visualisation_contoursets["likely_road_shape"][2].append(contour)# Red for likely road  
                    
        likely_roads.append(emmentaler_eroded)
            
    print(str(len(likely_roads)) + ' likely roads found.')
    
    likely_roads = sum(likely_roads)
    
    ## Next, dilate/erode to close any *small* gaps in road sections
    print("Dilating ...")
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(gap_close), int(gap_close)))
    likely_roads = cv2.dilate(likely_roads, kernel, iterations=1)        
    
    ## Skeletonize
    print("Skeletonizing ...")
    skeleton = skeletonize(likely_roads / 255.).astype(np.uint8) * 255
    contours = cv2.findContours(skeleton, cv2.RETR_LIST , cv2.CHAIN_APPROX_NONE)[0]
    visualisation_contoursets["likely_road_line"][2] = contours # Blue for likely road lines
    
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
    
        base64_images.append({"label": "Segmented map image", "image": base64.b64encode(cv2.imencode('.png', visualisation)[1]).decode("utf-8")}) 
        base64_images.append({"label": "Skeletonized likely roads", "image": base64.b64encode(cv2.imencode('.png', skeleton)[1]).decode("utf-8")}) 

        if show_images:
            cv2.imshow("Binary Image", binary_image)
            cv2.imshow('skeleton', skeleton) 
            cv2.imshow('likely_roads', visualisation) 
            cv2.waitKey(0)
    
    return contours, skeleton, base64_images