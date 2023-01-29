'''
@author: Stephen Gadd, Docuracy Ltd, UK

This code defines a function called find_shortest_path() that takes as input a list of 
linestrings, a modernity, a score, a width, a gap size, modern roads, and a transform. 
The function first selects a modern road by matching its 'id' attribute with the input 
modernity, and then it reprojects the endpoints of the modern road into the raster pixel 
CRS. Next, it creates a directed graph and adds nodes to the graph representing each 
endpoint of the linestrings, and adds edges between the nodes that represent the 
linestrings. The function then finds the closest endpoint to start_point and end_point 
and finds the shortest path between the closest start and closest end. Finally, it 
initializes variables to store the sum of scores and widths and the count of edges, and 
adds the score and width values of the edges to the running sum.

The merge_groups function takes as input a list of linestrings, a list of scores, a 
list of widths, a gap size, and a dataframe of modern roads. It starts by merging all 
the linestrings in the input list into a single MultiLineString object. Then, it iterates 
through the modern roads in the input dataframe, and for each modern road, it finds the 
shortest path between the start and end points of the modern road, using the merged 
linestring as the graph for the path finding algorithm. The function returns a 
MultiLineString object containing all the shortest paths found, along with a list of 
tuples containing the ID of the modern road, the sum of scores of the edges in the path, 
and the sum of widths of the edges in the path.

'''

import networkx as nx
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import linemerge
import itertools
from collections import defaultdict
import rasterio

def find_shortest_path(linestrings, modernity, score, width, gap_size, modern_roads, transform):
    print('Merging: '+modernity[0])

    # Select the modern road
    line = modern_roads[modern_roads['id'] == modernity[0]].geometry.iloc[0]
    ## Reproject its endpoints into the raster pixel CRS, switching row,col to col,row
    start_point = Point(rasterio.transform.rowcol(transform, *line.coords[0])[::-1])
    end_point = Point(rasterio.transform.rowcol(transform, *line.coords[-1])[::-1])
        
    ## Add in the modernity, score, and width attributes
    
    # Create a directed graph and add nodes to the graph representing each LineString endpoint
    G = nx.DiGraph()
    # Add nodes and edges for each LineString
    for i, ls in enumerate(linestrings):
        G.add_node(ls.coords[0], pos=ls.coords[0])
        G.add_node(ls.coords[-1], pos=ls.coords[-1])
        G.add_edge(ls.coords[0], ls.coords[-1], linestring=ls, weight=ls.length, score=score[i], width=width[i])
        G.add_edge(ls.coords[-1], ls.coords[0], linestring=LineString(ls.coords[::-1]), weight=ls.length, score=score[i], width=width[i])
        # Add edges to bridge shortest gaps between linestring pairs
        for ls2 in linestrings[i+1:]:
            closest_distance = float('inf')
            for endpoint1 in ls.coords[0], ls.coords[-1]:
                for endpoint2 in ls2.coords[0], ls2.coords[-1]:
                    distance = Point(endpoint1).distance(Point(endpoint2))
                    if distance < closest_distance:
                        closest_distance = distance
                        bridge_start, bridge_end = endpoint1, endpoint2
            if closest_distance < 500:
                G.add_edge(bridge_start, bridge_end, linestring=LineString([bridge_start, bridge_end]), weight=closest_distance*10) # weight to discourage use of gap-bridges
                G.add_edge(bridge_end, bridge_start, linestring=LineString([bridge_end, bridge_start]), weight=closest_distance*10) # weight to discourage use of gap-bridges
                
    # Find closest endpoint to start_point
    closest_start = None
    closest_start_dist = float("inf")
    for node in G.nodes():
        dist = start_point.distance(Point(node))
        if dist < closest_start_dist:
            closest_start = node
            closest_start_dist = dist
    # Find closest endpoint to end_point
    closest_end = None
    closest_end_dist = float("inf")
    for node in G.nodes():
        dist = end_point.distance(Point(node))
        if dist < closest_end_dist:
            closest_end = node
            closest_end_dist = dist
    
    # Find the shortest path between closest_start and closest_end
    try:
        path = nx.shortest_path(G, closest_start, closest_end, weight='weight')
    except nx.NetworkXNoPath:
        print('NetworkXNoPath')
        return None, [modernity[0],0,0]
    
    # Initialize variables to store the sum of scores and widths and the count of edges
    score_sum = 0
    width_sum = 0
    edge_count = 0
    
    linestrings = []
    for i in range(len(path)-1):
        linestrings.append(G.edges[path[i], path[i+1]]['linestring'])
        edge = G.edges[path[i], path[i+1]]
        # Extract the score and width values of the edge
        edge_score = edge.get('score', 0)
        edge_width = edge.get('width', 0)
        if not edge_score == 0:
            # Add the score and width values to the running sum
            score_sum += edge_score
            width_sum += edge_width
            edge_count += 1
    # Calculate the averages
    average_score = score_sum / edge_count if edge_count > 0 else 0
    average_width = width_sum / edge_count if edge_count > 0 else 0
    
    if modernity[0] == 'idC2464111-3B6F-4879-9666-0651B513C9B0':
        print(start_point,closest_start,end_point,closest_end)
        print(ls)
        print(path)
        print(average_score,average_width)
    
    coords = []
    for ls in linestrings:
        coords.extend(ls.coords)
    if len(coords) < 2:
        return None, [modernity[0],average_score,average_width]
            
    return LineString(coords), [modernity[0],average_score,average_width]

def merge_groups(line_strings, attributes, gap_size, modern_roads, transform, FILTER_SCORE):
    new_line_strings = []
    new_attributes = []
    
    # Group LineStrings by shared modernity
    line_string_groups = defaultdict(list)
    for i, line_string in enumerate(line_strings):
        if attributes[i]['score'] < FILTER_SCORE:
            continue
        if not attributes[i]['modernity'] == '':
            line_string_groups[attributes[i]['modernity']].append((line_string, attributes[i]))
        else:
            new_line_strings.append(line_string)
            new_attributes.append(attributes[i])
    
    # Create new sets of LineStrings and attributes based on merged groups
    for group in line_string_groups.values():
        # merged_line_string, merged_attributes = merge_linestrings([ls for ls, attr in group], [attr['modernity'] for ls, attr in group], [attr['score'] for ls, attr in group], [attr['width'] for ls, attr in group], gap_size)
        merged_line_string, merged_attributes = find_shortest_path([ls for ls, attr in group], [attr['modernity'] for ls, attr in group], [attr['score'] for ls, attr in group], [attr['width'] for ls, attr in group], gap_size, modern_roads, transform)
        if merged_line_string is not None:
            new_line_strings.append(merged_line_string)
            keys = ['modernity', 'score', 'width']
            merged_attributes_dict = dict(zip(keys, merged_attributes))
            new_attributes.append(merged_attributes_dict)
        else:
            new_line_strings.append(line_strings[0])
            new_attributes.append(attributes[0])
        
    return new_line_strings, new_attributes

