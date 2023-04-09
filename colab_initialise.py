import sys
sys.path.append('/content/ilastik-1.4.0-Linux/lib/python3.7/site-packages')

# Import modules for running ilastik prediction
from ilastik.experimental.api import from_project_file
import numpy
from xarray import DataArray
import imageio
from matplotlib import pyplot as plt

# Load map tile definitions
import json
map_defaults_file = "/content/desCartes/webapp/data/map_defaults.json"
with open(map_defaults_file, 'r') as file:
  map_defaults = json.load(file)
  
from ipyleaflet import Map, TileLayer, Rectangle
from ipywidgets import Layout

center = (52.74959372674117, -2.0214843750000004)
zoom = 7
defaultLayout=Layout(width='750px', height='750px') # Pixel dimesions of geotiff will be 4x these values
m = Map(center=center, zoom=zoom, layout=defaultLayout, scroll_wheel_zoom=True)

# Add the OS 6" basemap to the map
layer = TileLayer(url=map_defaults[0]["url"], attribution=map_defaults[0]["attribution"], min_zoom = 13)
m.add_layer(layer)

rectangle = None
def on_map_change(event):
    global rectangle
    def remove_rectangle():
        global rectangle
        if rectangle is not None and rectangle in m.layers:
            m.remove_layer(rectangle)
            rectangle = None
    if event.owner.zoom == 15:
        remove_rectangle()
        new_bounds = ((event.owner.south, event.owner.west),(event.owner.north, event.owner.east))
        rectangle = Rectangle(bounds=new_bounds, weight=5, color='red', fill_opacity=0.1, draggable=False)
        m.add_layer(rectangle)
    else:
        remove_rectangle()

# Observe the map and call the function when the zoom or centre change
m.observe(on_map_change, ['zoom', 'center'])

# Display the map
display(m)