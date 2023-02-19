import geopandas as gpd
from shapely.geometry import Point, LineString
import networkx as nx

# Load the modern road network and old road network GeoDataFrames
modern_roads = gpd.read_file('modern_roads.shp')
old_roads = gpd.read_file('old_roads.shp')

# Snap the endpoints of the old roads to the modern roads
tolerance = 50  # set a tolerance parameter for snapping
snapped_old_roads = []
for old_road in old_roads.geometry:
    start_point, end_point = old_road.boundary
    snapped_start = modern_roads.geometry.interpolate(modern_roads.geometry.project(start_point), normalized=True)
    snapped_end = modern_roads.geometry.interpolate(modern_roads.geometry.project(end_point), normalized=True)
    snapped_old_roads.append(LineString([snapped_start, snapped_end]))

# Create a graph of the road network
graph = nx.Graph()
for i, modern_road in modern_roads.iterrows():
    graph.add_node(i, geometry=modern_road.geometry)
for i, snapped_old_road in enumerate(snapped_old_roads):
    graph.add_node(i+len(modern_roads), geometry=snapped_old_road)
for i, modern_road1 in modern_roads.iterrows():
    for j, modern_road2 in modern_roads.iterrows():
        if i != j and modern_road1.geometry.intersects(modern_road2.geometry):
            graph.add_edge(i, j)
    for j, snapped_old_road in enumerate(snapped_old_roads):
        if modern_road1.geometry.intersects(snapped_old_road):
            graph.add_edge(i, j+len(modern_roads))

# Compute the shortest path between all pairs of nodes
all_pairs = nx.all_pairs_dijkstra_path(graph)

# Extract the shortest path between each pair of old road endpoints
filler_segments = []
for old_road in snapped_old_roads:
    start_point, end_point = old_road.boundary
    start_node = min(range(len(modern_roads)), key=lambda i: modern_roads.geometry[i].distance(start_point))
    end_node = min(range(len(modern_roads)), key=lambda i: modern_roads.geometry[i].distance(end_point))
    path = all_pairs[start_node][end_node]
    filler_segment = LineString([graph.nodes[n]['geometry'] for n in path])
    filler_segments.append(filler_segment)

# Create a GeoDataFrame of the filler segments and save to file
filler_segments_gdf = gpd.GeoDataFrame(geometry=filler_segments)
filler_segments_gdf.to_file('filler_segments.shp')
