import networkx as nx
from shapely.geometry import LineString, MultiLineString
import itertools
from collections import defaultdict

def merge_linestrings(linestrings, modernity, score, width, gap_size):
    print('Merging: '+modernity[0])
    # Create a directed graph and add nodes to the graph representing each LineString
    G = nx.DiGraph()
    for i, ls in enumerate(linestrings):
        G.add_node(i, geometry=ls, score=score[i], width=width[i])
    # Add edges between nodes representing LineStrings that can be merged
    for i, ls1 in enumerate(linestrings):
        for j, ls2 in enumerate(linestrings):
            if i != j:
                if ls1.distance(ls2) <= gap_size:
                    G.add_edge(i, j, weight=ls1.length + ls2.length)
    # Find the longest path through the graph using Dijkstra's algorithm
    try:
        print(G)
        end = len(G)-1
        pred, dist = nx.dijkstra_predecessor_and_distance(G, 0, weight='weight')
    except nx.NetworkXNoPath:
        print('NetworkXNoPath')
        return None, None
    # Reconstruct the path from the Dijkstra output
    node = pred.get(end)
    if node is None:
        return None, None
    path = [end]
    while node is not None:
        path.append(node)
        node = pred.get(node)
    path = list(reversed(path))

    # Create the new merged LineString by concatenating the coordinates of the LineStrings in the path
    merged_geometry = LineString( list(itertools.chain.from_iterable(G.nodes[node]['geometry'].coords for node in path)) )  
    
    # Compute the average values of the attributes
    length = sum(G.nodes[i]['geometry'].length for i in range(len(G)))
    score = sum(G.nodes[i]['score'] * G.nodes[i]['geometry'].length for i in path) / length
    width = sum(G.nodes[i]['width'] * G.nodes[i]['geometry'].length for i in path) / length
    
    return merged_geometry, [modernity[0], score, width]

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
        merged_line_string, merged_attributes = merge_linestrings([ls for ls, attr in group], [attr['modernity'] for ls, attr in group], [attr['score'] for ls, attr in group], [attr['width'] for ls, attr in group], gap_size)
        if merged_line_string is not None:
            new_line_strings.append(merged_line_string)
            keys = ['modernity', 'score', 'width']
            merged_attributes_dict = dict(zip(keys, merged_attributes))
            new_attributes.append(merged_attributes_dict)
        
    return new_line_strings, new_attributes

