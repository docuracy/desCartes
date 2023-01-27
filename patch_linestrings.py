import networkx as nx
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import linemerge
import itertools
from collections import defaultdict
from pickle import NONE

def find_shortest_path(linestrings, modernity, score, width, gap_size, start_point = Point(0,10000), end_point = Point(10000,0)):
    print('Merging: '+modernity[0])
    # Create a directed graph and add nodes to the graph representing each LineString endpoint
    G = nx.DiGraph()
    # Add nodes and edges for each LineString
    for i, ls in enumerate(linestrings):
        G.add_node(ls.coords[0], pos=ls.coords[0])
        G.add_node(ls.coords[-1], pos=ls.coords[-1])
        G.add_edge(ls.coords[0], ls.coords[-1], linestring=ls, weight=ls.length)
        G.add_edge(ls.coords[-1], ls.coords[0], linestring=LineString(ls.coords[::-1]), weight=ls.length)
        if modernity[0] == 'id92CC9581-BCCE-4892-8D4B-6D71E531186A':
            print(ls)
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
                if modernity[0] == 'id92CC9581-BCCE-4892-8D4B-6D71E531186A':
                    print(LineString([bridge_start, bridge_end]))
                # print('Added edge: '+str(int(closest_distance)))
            # else:
                # print('Skipped adding edge: '+str(int(closest_distance)))

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
            
    if modernity[0] == 'id92CC9581-BCCE-4892-8D4B-6D71E531186A':
        print(start_point,closest_start,end_point,closest_end)
    
    # Find the shortest path between closest_start and closest_end
    try:
        path = nx.shortest_path(G, closest_start, closest_end, weight='weight')
    except nx.NetworkXNoPath:
        print('NetworkXNoPath')
        return None, [modernity[0],0,0]
    
    linestrings = []
    for i in range(len(path)-1):
        linestrings.append(G.edges[path[i], path[i+1]]['linestring'])
    coords = []
    for ls in linestrings:
        coords.extend(ls.coords)
    if len(coords) < 2:
        return None, [modernity[0],0,0]
    return LineString(coords), [modernity[0],0,0]

def merge_groups(line_strings, attributes, gap_size):
    new_line_strings = []
    new_attributes = []
    
    # Group LineStrings by shared modernity
    line_string_groups = defaultdict(list)
    for i, line_string in enumerate(line_strings):
        if not attributes[i]['modernity'] == '':
            line_string_groups[attributes[i]['modernity']].append((line_string, attributes[i]))
        else:
            new_line_strings.append(line_string)
            new_attributes.append(attributes[i])
    
    # Create new sets of LineStrings and attributes based on merged groups
    for group in line_string_groups.values():
        # merged_line_string, merged_attributes = merge_linestrings([ls for ls, attr in group], [attr['modernity'] for ls, attr in group], [attr['score'] for ls, attr in group], [attr['width'] for ls, attr in group], gap_size)
        merged_line_string, merged_attributes = find_shortest_path([ls for ls, attr in group], [attr['modernity'] for ls, attr in group], [attr['score'] for ls, attr in group], [attr['width'] for ls, attr in group], gap_size)
        if merged_line_string is not None:
            new_line_strings.append(merged_line_string)
            keys = ['modernity', 'score', 'width']
            merged_attributes_dict = dict(zip(keys, merged_attributes))
            new_attributes.append(merged_attributes_dict)
        else:
            new_line_strings.append(line_strings[0])
            new_attributes.append(attributes[0])
        
    return new_line_strings, new_attributes

