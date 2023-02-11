'''
@author: Stephen Gadd, Docuracy Ltd, UK

'''

import cv2
import geopandas as gpd
from rtree import index
import numpy as np
from sklearn.cluster import DBSCAN
import math
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle
import io
import base64

    
def find_areas(grayscale_image, template_dir = './data/templates', template_filenames = ['tree-broadleaf.png', 'tree-conifer.png'], thresholds = [.7, .7], SHOW_IMAGES = False):
    
    ## Try rewriting using CV_RETR_FLOODFILL to find contours bounding template matches
    
    print("Loading templates ...")
    max_template_area = 0
    centrepoints = []
    for i, template_filename in enumerate(template_filenames):
        print("Matching: "+template_filename)
        template = cv2.imread(f"{template_dir}/{template_filename}", 0)
        max_template_area = max(max_template_area, template.shape[0] * template.shape[1])
        res = cv2.matchTemplate(grayscale_image, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= thresholds[i])
        coords = list(zip(*loc[::-1]))
        centres = [(x + template.shape[1] // 2, y + template.shape[0] // 2) for (x, y) in coords]
        centrepoints.extend(centres)
    print("... Done. " + str(len(centrepoints)) + " matches found:")
    print("max_template_area: " + str(max_template_area))
        
    # Identify clusters using Density-Based Spatial Clustering of Applications with Noise (DBSCAN)
    # The eps parameter specifies the maximum distance between two points to be considered as part of the same cluster, 
    # and the min_samples parameter specifies the minimum number of points required to form a dense region.
    print("Starting DBSCAN ...")
    # dbscan = DBSCAN(eps = 2 * math.sqrt(max_template_area), min_samples = 3)
    dbscan = DBSCAN(eps = 3 * math.sqrt(max_template_area), min_samples = 10)
    dbscan.fit(centrepoints)
    labels = dbscan.labels_
    labels = labels.astype(int)
    unique_labels = set(labels)
    print("... Done. Unique labels:")
    print("Filling arrays ...")

    cluster_points = {}
    for i, label in enumerate(labels):
        if label not in cluster_points:
            cluster_points[label] = []
        cluster_points[label].append(centrepoints[i])
    print("...  Cluster points:")
    
    bounding_boxes = []
    for label in cluster_points.keys():
        if label == -1:
            continue
        cluster = np.array(cluster_points[label])
        min_x, min_y = np.min(cluster, axis=0)
        max_x, max_y = np.max(cluster, axis=0)
        bounding_boxes.append([min_x, min_y, max_x, max_y])
    print("... Done. Bounding boxes:")
    
    # Find the contours in the binarised image, filter based on the area threshold and contour closure, and spatially-index the contours' bounding boxes
    print("Finding contours ...")
    _, binary = cv2.threshold(grayscale_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    # contours = [c for c in contours if cv2.contourArea(c) > 4 * max_template_area and len(c) > 2]
    
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    final_contours = []
    for i, c in enumerate(contours):
        area = cv2.contourArea(c)
        if area > 4 * max_template_area and len(c) > 2:
            parent = hierarchy[0][i][3]
            if parent == -1 or cv2.contourArea(contours[parent]) <= area:
                final_contours.append(c)
    
    contours = final_contours
    
    print(str(len(contours))+" found.")
    print("... indexing ...")
    boundingRects = [cv2.boundingRect(c) for c in contours]
    bboxes = [( [b[0], b[1], b[0]+b[2], b[1]+b[3]] ) for b in boundingRects]
    
    p = index.Property()
    idx = index.Index(properties = p)
    for i, bbox in enumerate(bboxes):
        idx.insert(i, bbox)
    print("... Done")

    print("Finding intersections ...")
    # likely_areas = []
    # for point_bbox in bounding_boxes:
    #     candidate_bboxes = list(idx.intersection(point_bbox))
    #     for i in candidate_bboxes:
    #         c = contours[i]
    #         count = 0
    #         for p in cluster_points[bounding_boxes.index(point_bbox)]:
    #             p = np.array(p, dtype=np.float32)
    #             if cv2.pointPolygonTest(c, p, False) >= 0:
    #                 count += 1
    #             if count >= 3:
    #                 likely_areas.append(c)
    #                 break
    
    likely_areas = []
    for i, point_bbox in enumerate(bounding_boxes):
        cluster_points_i = cluster_points[i]
        candidate_bboxes = list(idx.intersection(point_bbox))
        min_area = float('inf')
        min_area_contour = None
        for j in candidate_bboxes:
            c = contours[j]
            if cv2.contourArea(c) < min_area:
                count = 0
                for p in cluster_points_i:
                    p = np.array(p, dtype=np.float32)
                    if cv2.pointPolygonTest(c, p, False) >= 0:
                        count += 1
                    if count >= 3:
                        min_area = cv2.contourArea(c)
                        min_area_contour = c
                        break
        if min_area_contour is not None:
            likely_areas.append(min_area_contour)

    
    
    print("... Done")
        
    likely_contours = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2BGR)
    likely_areas = [contour.reshape(-1, 2) for contour in likely_areas]
    
    fig, ax = plt.subplots(1)
    ax.imshow(likely_contours)
    
    for contour in likely_areas:
        poly = Polygon(contour, facecolor="#FF7F7F3F")
        ax.add_patch(poly)
        ax.plot(contour[:, 0], contour[:, 1], color="#FF00007F", linewidth=1)
        
    diameter = np.sqrt(max_template_area)
    for template_match in centrepoints:
        x, y = template_match
        ax.add_artist(plt.Circle((x, y), diameter/2, color="#FFFF003F"))
        
    for bounding_box in bounding_boxes:
        min_x, min_y, max_x, max_y = bounding_box
        rect = Rectangle((min_x, min_y), max_x - min_x, max_y - min_y, fill=False, linewidth=2, edgecolor="#FFFF003F")
        ax.add_patch(rect)
    
    if SHOW_IMAGES:
        plt.show()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    base64_shaded = base64.b64encode(buf.read()).decode('utf-8')
    plt.close()
    
    return likely_areas, base64_shaded
