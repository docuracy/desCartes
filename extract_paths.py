# -*- coding: utf-8 -*-
"""

@author: Stephen Gadd, Docuracy Ltd, UK

"""

######################################################################################
"""
This code defines a function extract_paths that takes an image, an angle alpha, a 
number of backsteps, and a minimum length as input. The function first creates a copy 
of the image and initializes an array to store the paths.

The function then iterates through the pixels in the image and, for each black pixel, 
performs a breadth-first search (BFS) to find the longest path. The function 
initializes a queue with the starting point, a set to store the visited points, and a 
list to store the path. It then performs BFS by taking the next point from the queue, 
adding it to the path and visited set, and changing the value of the point in the copy 
to white. The function then gets the neighbours of the point using the get_neighbours 
function and adds the neighbours to the queue if they have not been visited.

After the BFS is completed, the function reverses the path and continues the search by 
setting the queue to the path and repeating the process. When the search is completed, 
the function checks if the length of the path is greater than the minimum length and, 
if it is, converts the path to a LineString and adds it to the paths array. Finally, 
the function returns the paths array.

This code also defines a function get_neighbours that takes a point, a path, an image, 
an angle alpha, and a number of backsteps as input. The function first converts the 
angle alpha from degrees to radians and gets the x and y coordinates of the point. It 
then initializes an array to store the neighbours and an array to store the angles.

The function then checks if the length of the path is greater than or equal to 
backsteps-1 and, if it is, loops through the previous backsteps points and calculates 
the angle between each pair of points, adding the angles to the angles array.

The function then checks the 8 neighbouring pixels of the point. For each neighbour, it 
checks if the neighbour is within the bounds of the image and is black. If it is, it 
checks if the angles array is empty. If it is, it adds the neighbour to the neighbours 
array. If the angles array is not empty, the function calculates the angle between the 
point at the end of the path and the neighbour and adds the angle to the angles array. 
It then calculates the range of angles in the angles array and checks if it is within 
the allowed range defined by alpha_radians. If it is, the function adds the neighbour 
to the neighbours array.

The function also includes a helper function angle that calculates the angle between 
two points. This function gets the x and y coordinates of the points and calculates 
the angle between them using the atan2 function. If the result is greater than Pi, it 
subtracts the angle from 2*Pi and returns the result.

"""

import math
from shapely.geometry import LineString

def extract_paths(image, alpha, backsteps, minlength, tolerance):
    # create a copy of the image to modify
    copy = image.copy()
    # initialize an array to store the paths
    paths = []
    # get the width and height of the image
    width, height = image.shape
    # iterate through the pixels in the image
    for y in range(height):
        print("{}/{}".format(y, height))
        for x in range(width):
        # for x in range(int(width/20)):
            # if the pixel is black, perform DFS to find the longest path
            if copy[x, y] == 0:
                # initialize the stack with the starting point
                stack = [(x, y)]
                # initialize a set to store the visited points
                visited = set()
                # initialize a list to store the path
                path = []
                def check_neighbours():
                    # perform DFS
                    while stack:
                        # get the next point to visit
                        point = stack.pop()
                        # add the point to the path and visited set
                        path.append(point)
                        visited.add(point)
                        # change the value of the point in the copy to white
                        copy[point[0], point[1]] = 1
                        # get the neighbours of the point
                        neighbours = get_neighbours(point, path, image, width, height, alpha, backsteps)
                        # add the neighbours to the stack if they have not been visited
                        for neighbour in neighbours:
                            if neighbour not in visited:
                                stack.append(neighbour)
                                break # Use only the first neighbour
                check_neighbours()
                # reverse the path and continue the search
                path.reverse()
                stack = [path[-1]]
                check_neighbours()
                
                if len(path) > minlength:
                    # convert the path to a LineString, simplify, and add it to the array
                    path = LineString(path)
                    path = path.simplify(tolerance)
                    paths.append(path)
    return paths


def get_neighbours(point, path, image, width, height, alpha, backsteps):
    # convert alpha from degrees to radians
    alpha_radians = math.radians(alpha)
    # get the x and y coordinates of the point
    x, y = point
    # initialize an array to store the neighbours
    neighbours = []

    # initialize an array to store the angles
    angles = []
    if len(path) >= backsteps - 1:
        # loop through previous backsteps points
        for i in range(3, backsteps):
            # calculate the angle between the point and the next point along the path, and add the angle to the array
            angles.append(angle(path[-backsteps + 1], path[-backsteps + i]))

    # check the 8 neighbouring pixels
    for dx in [-1, 0, 1]:
        for dy in [-1, 0, 1]:
            # skip the current point
            if dx == 0 and dy == 0:
                continue
            # check if the neighbour is within the bounds of the image and is black
            if (
                (0 <= x + dx < width)
                and (0 <= y + dy < height)
                and (image[x + dx, y + dy] == 0)
            ):
                # check if the angle between the points is within the allowed range
                if len(angles) == 0:
                    # add the neighbour to the array
                    neighbours.append((x + dx, y + dy))
                else:
                    angles.append(angle(path[-backsteps + 1], (x + dx, y + dy)))
                    angle_range = max(angles) - min(angles)
                    if angle_range <= alpha_radians:
                        # add the neighbour to the array
                        neighbours.append((x + dx, y + dy))
                    angles.pop()

    return neighbours


def angle(p1, p2):
    # get the x and y coordinates of the points
    x1, y1 = p1
    x2, y2 = p2
    # calculate the angle between the points
    result = math.atan2(y2 - y1, x2 - x1)
    if result > math.pi:
        # subtract the angle from 2*Pi
        result = 2 * math.pi - result
    return result
