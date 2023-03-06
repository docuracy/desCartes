import math

def unit_vector(p1, p2):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.sqrt(dx*dx + dy*dy)
    if length > 0:
        return (dx/length, dy/length)
    else:
        return (0, 0)