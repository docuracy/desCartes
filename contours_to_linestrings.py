# -*- coding: utf-8 -*-
"""

@author: Stephen Gadd, Docuracy Ltd, UK

"""

import shapely.geometry as geom
from shapely.geometry import LineString, Point
import math

def contours_to_linestrings(contours, tolerance, angle_threshold):
    angle_threshold = angle_threshold * math.pi / 180 # convert to radians
    all_points = set()
    linestrings = []
    
    def split_linestring_on_angle(linestring):
    
        def angle(p1, p2, p3):
            v1 = (p2.x - p1.x, p2.y - p1.y)
            v2 = (p3.x - p2.x, p3.y - p2.y)
            dot = v1[0]*v2[0] + v1[1]*v2[1]
            det = v1[0]*v2[1] - v1[1]*v2[0]
            return math.atan2(det, dot)
    
        split_points = []
        for i in range(1, len(linestring.coords) - 1):
            p1 = Point(linestring.coords[i-1])
            p2 = Point(linestring.coords[i])
            p3 = Point(linestring.coords[i+1])
            angle_result = angle(p1, p2, p3)
            if angle_result > angle_threshold:
                split_points.append(i)
        start = 0
        for split_point in split_points:
            linestrings.append(LineString(linestring.coords[start:split_point+1]))
            start = split_point
        linestrings.append(LineString(linestring.coords[start:]))
    
    def add_linestring(points):
        if len(points) > 1:
            linestring = geom.LineString(points)
            linestring = linestring.simplify(tolerance)
            if linestring.length > 0:
                split_linestring_on_angle(linestring)
    
    for cnt in contours:
        if len(cnt) < 2:
            continue
        points = [tuple(cnt[i][0]) for i in range(len(cnt))]
        start = 0
        for i in range(1, len(points)):
            if points[i] in all_points:
                add_linestring(points[start:i])
                start = i
            all_points.add(points[i])
        if start < len(points) - 2:
            add_linestring(points[start:len(points)])
    
    return linestrings


