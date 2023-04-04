import math
import cv2
import numpy as np
from wand.image import Image
from wand.color import Color

def unit_vector(p1, p2):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.sqrt(dx*dx + dy*dy)
    if length > 0:
        return (dx/length, dy/length)
    else:
        return (0, 0)
    
def imshow_size(label, image, desired_height = 600, wait = False):
    height, width = image.shape[:2]
    resize_factor = desired_height / height
    image = cv2.resize(image, (int(width * resize_factor), desired_height))
    cv2.imshow(label, image)
    if wait:
        print('Visualising. Press any key to continue:')
        cv2.waitKey(0)

def ends_and_junctions(skeleton):
    skeleton = skeleton.astype(bool)
    with Image(width=skeleton.shape[1], height=skeleton.shape[0], background=Color('white')) as img:
        # Create binary image from skeleton
        with img.clone() as binImg:
            binImg.type = 'bilevel'
            binImg.compression = 'no'
            binImg.alpha_channel = 'remove'
            binImg.import_pixels(0, 0, binImg.width, binImg.height, 'I', 'char', skeleton.tobytes())

            # Find line-ends using Top-Hat Morphology
            lineEnds = """
            3>:
                0,0,-
                0,1,1
                0,0,-;
            3>:
                0,0,0
                0,1,0
                0,0,1
            """
            with binImg.clone() as endsImage:
                endsImage.morphology(method='hit_and_miss', kernel=lineEnds)

                # Get endpoints as array of coordinate indices
                endpoints = np.transpose(np.nonzero(np.array(endsImage)))

            # Find line-junctions using Top-Hat Morphology
            lineJunctions = """
            3>:
                1,-,1
                -,1,-
                -,1,-;
            3>:
                -,1,-
                -,1,1
                1,-,-;
            3>:
                1,-,-
                -,1,-
                1,-,1
            """
            with binImg.clone() as junctionsImage:
                junctionsImage.morphology(method='hit_and_miss', kernel=lineJunctions)

                # Get junctions as array of coordinate indices
                junctions = np.transpose(np.nonzero(np.array(junctionsImage)))

    return endpoints[:, :2], junctions[:, :2]