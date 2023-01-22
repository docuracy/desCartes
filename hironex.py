# -*- coding: utf-8 -*-
"""
Created on Tue Jan 01 11:56:06 2019

@author: Johannes H. Uhl, University of Colorado Boulder, USA.

Adapted for use with UK Ordnance Survey data and historical maps by Stephen Gadd, Docuracy Ltd, UK

"""

#### HIRONEX - HIstorical ROad NEtwork EXtractor ####
######################################################################################
#### Hironex is a small geospatial python tool 
#### that reads a scanned and georeferenced historical map
#### and a vector dataset representing the modern road network
#### HIRONEX then calculates an indicator that quanitifies the likelihood,
#### for each road segment, of overlapping with a road symbol in the historical map
#### This continuous road overlap indicator (ROI) is then thresholded
#### using ck-means or regular k-means to generate an approximation 
#### of the historical road network, as a subnetwork of the modern road network.
#### This approach does not extract roads present in the map but not in the modern data,
#### i.e., road network shrinkage / disappeared roads are not taken into account.
######################################################################################

#### INPUTS:
#### vector_proj: a shapefile holding the modern road network line geometries
#### mapfile: a GeoTIFF file holding the historical map.
#### vector_proj and mapfile must be in the same CRS, and optimally cover the same area.
######################################################################################

#### OUTPUT:
#### At the location of vector_proj, a shapefile with suffix
#### _w_roi_XX_YY.shp' will be created.
#### XX and YY are two user speficied parameters crosssect_dist and crosssect_length (see below).
#### This shapefile holds two new columns:
#### 'roi' with the road overlap indicator, and
#### 'cluster' indicating (1) historical road or (0) modern road.
#### The script also visualizes both ROI and the clustering results as PNG files in folder datadir.
######################################################################################

#### PARAMETERS:
#### crosssect_dist = distance between crosssections along the road axis in m
#### crosssect_length = extension of the crosssection to the left and right of road in m.
#### target_band_length = the height dimension of the axial images used to calculate the ROI in pixels
#### target_band_length defines the height of the axial image. 
#### if a road segment has more than target_band_length cross-sections, a random sample of N = target_band_length is used.
#### DO_CKMEANS: Boolean parameter, indicating of cKmeans is used (slower), or regular kmeans (faster)
#### See https://doi.org/10.1016/j.compenvurbsys.2022.101794 for details on these parameters.
######################################################################################

#### SCRIPT SECTIONS:
#### sample_map: Generates cross-sectional sampling geometries and collects map color information.
#### calc_roi: Calculates the ROI, performs clustering and exports results to SHP
#### vis_roi: Visualizes the results.

######################################################################################
#### DEPENDENCIES:
#### ckmeans_lib, containing code for ckmeans 1d-clustering algorithm.
#### adapted from https://github.com/llimllib/ckmeans, Thanks to Bill Mill.

######################################################################################
#### REFERENCE:
#### Uhl, J. H., Leyk, S., Chiang, Y. Y., & Knoblock, C. A. (2022). Towards the automated 
#### large-scale reconstruction of past road networks from historical maps. 
#### Computers, Environment and Urban Systems, 94, 101794.

######################################################################################
#### Created 2022 by Johannes H. Uhl, 
#### Earth Lab, Cooperative Institute for Research in Environmental Sciences, 
#### University of Colorado Boulder, Boulder, CO 80309, USA &
#### Institute of Behavioral Science, University of Colorado Boulder, 
#### Boulder, CO 80309, USA
######################################################################################

import sys, os, subprocess
from shapely.geometry import LineString, Point, Polygon
from shapely import wkt
import math
import pandas as pd
from osgeo import gdal
from osgeo import ogr
from sklearn.cluster import KMeans
import numpy as np
import geopandas as gp
import matplotlib.pyplot as plt
from scipy.integrate import trapz
import ckmeans_lib ### from https://github.com/llimllib/ckmeans, thanks to Bill Mill
import cv2 as cv
from tiles_to_tiff import create_geotiff

######################################################################################

#datadir = 'FOLDER FOR OUTPUTS'
#vector_proj = 'PATH TO CONTEMPORARY VECTOR ROAD NETWORK (SHP)'

ogr2ogr = r'C:\OSGeo4W\bin\ogr2ogr.exe'
datadir = './data'

extent = [-0.627918,51.636914,-0.617194,51.642220]
raster_tile_url = 'https://api.maptiler.com/tiles/uk-osgb10k1888/{z}/{x}/{y}.jpg?key=U2vLM8EbXurAd3Gq6C45'
raster_tile_zoom = 17
geotiff_name = 'geo.tiff'

roadfile = 'oproad_gb_linestrings.gpkg'
shapefile_name = 'oproad_gb_roadlink.shp'

refresh_sources = True
    
if refresh_sources:
#     mapfile = create_geotiff (raster_tile_url, datadir, geotiff_name, extent, raster_tile_zoom)
# else:
    mapfile = datadir + '/' + geotiff_name

######################################################################################
crosssect_length = 70 ### increase this if there are offsets between datasets
crosssect_dist = 25 ### increase this for faster processing
target_band_length=20 
######################################################################################
## Construct road template
## Roads on OS 6-inch projected at 600dpi are typically 6px internal width with 3px linewidth
road_width = 8 ###  width between lines
road_colour = (255,255,255)
roadline_width = 3
roadline_colour = (0,0,0)
background_colour = (255,255,255)
road_template = np.zeros((1,road_width+roadline_width*4,3), np.uint8)
road_template[:] = background_colour
road_template[:,roadline_width:2*roadline_width-1] = roadline_colour
road_template[:,2*roadline_width:2*roadline_width+road_width-1] = road_colour
road_template[:,2*roadline_width+road_width:3*roadline_width+road_width-1] = roadline_colour
road_template = cv.cvtColor(road_template, cv.COLOR_BGR2GRAY) ## Matching requires grayscale
match_template=True
######################################################################################
DO_CKMEANS=False ## if False, use regular k-means

sample_map=True
calc_roi=True
vis_roi=True
######################################################################################

if sample_map:

    ##############################################################################
    ## http://wikicode.wikidot.com/get-angle-of-line-between-two-points
    ## angle between two points
    def getAngle(pt1, pt2):
        x_diff = pt2.x - pt1.x
        y_diff = pt2.y - pt1.y
        return math.degrees(math.atan2(y_diff, x_diff))
    
    ## start and end points of chainage tick
    ## get the first end point of a tick
    def getPoint1(pt, bearing, dist):
        angle = bearing + 90
        bearing = math.radians(angle)
        x = pt.x + dist * math.cos(bearing)
        y = pt.y + dist * math.sin(bearing)
        return Point(x, y)
    ## get the second end point of a tick
    def getPoint2(pt, bearing, dist):
        bearing = math.radians(bearing)
        x = pt.x + dist * math.cos(bearing)
        y = pt.y + dist * math.sin(bearing)
        return Point(x, y)
    
    def createPerpendLines(input_lyr_name,distance,tick_length):
        ## set the driver for the data
        driver = ogr.GetDriverByName("Esri Shapefile")
        ## open the GDB in write mode (1)
        inds = driver.Open(input_lyr_name, 0)
          
        ## distance between each points
        #distance = 10
        ## the length of each tick
        #tick_length = 20
        
        ## output tick line fc name
        output_lns = input_lyr_name.replace('.shp',"{0}_{1}_lines.shp".format(distance, tick_length))
        #print (output_lns)
        outds = driver.CreateDataSource(output_lns)
            
        ## list to hold all the point coords
        list_points = []        
        lyr = inds.GetLayer()
    
        ## create a new line layer with the same spatial ref as lyr
        out_ln_lyr = outds.CreateLayer('', lyr.GetSpatialRef(), ogr.wkbLineString)
        
        ## distance/chainage attribute
        chainage_fld = ogr.FieldDefn("CHAINAGE", ogr.OFTReal)
        linefid_fld = ogr.FieldDefn("LINEFID", ogr.OFTInteger)
        out_ln_lyr.CreateField(chainage_fld)
        out_ln_lyr.CreateField(linefid_fld)
        ## check the geometry is a line
        first_feat = lyr.GetFeature(1)
        
        allfeatcount = lyr.GetFeatureCount()
        featcount=0
        ## accessing linear feature classes using FileGDB driver always returns a MultiLinestring
        if first_feat.geometry().GetGeometryName() in ["LINESTRING", "MULTILINESTRING"]:
            for ln in lyr:
                featcount+=1
                print ('creating transsection geometries per road segment...',featcount,'/',allfeatcount)
                
                currfid = ln.GetFID()
                
                ## list to hold all the point coords
                list_points = []
                ## set the current distance to place the point
                current_dist = distance
                ## get the geometry of the line as wkt
                line_geom = ln.geometry().ExportToWkt()
                line_geom = line_geom.replace(' too_big','')
    
                ## make shapely MultiLineString object
                #print (line_geom)
                shapely_line = LineString(wkt.loads(line_geom))

                ## get the total length of the line
                line_length = shapely_line.length
                ## append the starting coordinate to the list
                list_points.append(Point(list(shapely_line.coords)[0]))
                ## https://nathanw.net/2012/08/05/generating-chainage-distance-nodes-in-qgis/
                ## while the current cumulative distance is less than the total length of the line
                while current_dist < line_length:
                    ## use interpolate and increase the current distance
                    list_points.append(shapely_line.interpolate(current_dist))
                    current_dist += distance
                ## append end coordinate to the list
                list_points.append(Point(list(shapely_line.coords)[-1]))
        
                ## add lines to the layer
                ## this can probably be cleaned up better
                ## but it works and is fast!
                for num, pt in enumerate(list_points, 1):
                    ## start chainage 0
                    if num == 1:
                        angle = getAngle(pt, list_points[num])
                        line_end_1 = getPoint1(pt, angle, tick_length/2)
                        angle = getAngle(line_end_1, pt)
                        line_end_2 = getPoint2(line_end_1, angle, tick_length)
                        tick = LineString([(line_end_1.x, line_end_1.y), (line_end_2.x, line_end_2.y)])
                        feat_dfn_ln = out_ln_lyr.GetLayerDefn()
                        feat_ln = ogr.Feature(feat_dfn_ln)
                        feat_ln.SetGeometry(ogr.CreateGeometryFromWkt(tick.wkt))
                        feat_ln.SetField("CHAINAGE", 0)
                        feat_ln.SetField("LINEFID", currfid)
                        out_ln_lyr.CreateFeature(feat_ln)
        
                    ## everything in between
                    if num < len(list_points) - 1:
                        angle = getAngle(pt, list_points[num])
                        line_end_1 = getPoint1(list_points[num], angle, tick_length/2)
                        angle = getAngle(line_end_1, list_points[num])
                        line_end_2 = getPoint2(line_end_1, angle, tick_length)
                        tick = LineString([(line_end_1.x, line_end_1.y), (line_end_2.x, line_end_2.y)])
                        feat_dfn_ln = out_ln_lyr.GetLayerDefn()
                        feat_ln = ogr.Feature(feat_dfn_ln)
                        feat_ln.SetGeometry(ogr.CreateGeometryFromWkt(tick.wkt))
                        feat_ln.SetField("CHAINAGE", distance * num)
                        feat_ln.SetField("LINEFID", currfid)
                        out_ln_lyr.CreateFeature(feat_ln)
        
                    ## end chainage
                    if num == len(list_points):
                        angle = getAngle(list_points[num - 2], pt)
                        line_end_1 = getPoint1(pt, angle, tick_length/2)
                        angle = getAngle(line_end_1, pt)
                        line_end_2 = getPoint2(line_end_1, angle, tick_length)
                        tick = LineString([(line_end_1.x, line_end_1.y), (line_end_2.x, line_end_2.y)])
                        feat_dfn_ln = out_ln_lyr.GetLayerDefn()
                        feat_ln = ogr.Feature(feat_dfn_ln)
                        feat_ln.SetGeometry(ogr.CreateGeometryFromWkt(tick.wkt))
                        feat_ln.SetField("CHAINAGE", int(line_length))
                        feat_ln.SetField("LINEFID", currfid)
                        out_ln_lyr.CreateFeature(feat_ln)
        
        del inds
        del outds
        return output_lns
    
    
    def interpolPointsAlongLines(input_lyr_name,cross_sect_pts,distance):
    
        driver = ogr.GetDriverByName("Esri Shapefile")
        ## open the GDB in write mode (1)
        inds = driver.Open(input_lyr_name, 0)    
        output_lns = cross_sect_pts
        #print (output_lns)
        outds = driver.CreateDataSource(output_lns)            
        lyr = inds.GetLayer()    
        ## create a new line layer with the same spatial ref as lyr
        out_ln_lyr = outds.CreateLayer('', lyr.GetSpatialRef(), ogr.wkbPoint)
        
        ## distance/chainage attribute
        chainage_fld = ogr.FieldDefn("CHAINAGE", ogr.OFTReal)
        linefid_fld = ogr.FieldDefn("LINEFID", ogr.OFTInteger)
        out_ln_lyr.CreateField(chainage_fld)
        out_ln_lyr.CreateField(linefid_fld)
        feat_dfn_ln = out_ln_lyr.GetLayerDefn()
    
        allfeatcount = lyr.GetFeatureCount()
        featcount=0
        for feature in lyr:  
            featcount+=1
            print ('creating sampling locations per transsection...',featcount,'/',allfeatcount)            
            fidd=feature.GetField('LINEFID')
            pointsList=[]
            geom = feature.GetGeometryRef() 
            geomPolyline = wkt.loads(geom.ExportToWkt())  
            polyLength =  geomPolyline.length            
            for x in range(0,int(polyLength),int(distance)):
                pointsList.append(geomPolyline.interpolate(x))  # interpolating points along each line
    
            for pt in pointsList:
                point1 = ogr.Geometry(ogr.wkbPoint)
                point1.AddPoint(pt.x,pt.y)        
                outwkt =  point1.ExportToWkt()        
                feat_ln = ogr.Feature(feat_dfn_ln)
                feat_ln.SetGeometry(ogr.CreateGeometryFromWkt(outwkt))
                feat_ln.SetField("CHAINAGE", feature.GetField('CHAINAGE'))
                feat_ln.SetField("LINEFID", fidd)
          
                out_ln_lyr.CreateFeature(feat_ln)
                feat_ln = geom = None  # destroy these
        del inds
        del outds
            
    #############################################################################
    
    raster = gdal.Open(mapfile)
    gt =raster.GetGeoTransform()
    pixelSizeX = gt[1]
    pixelSizeY =-gt[5]
    cellsize=max(1,0.5*(pixelSizeX+pixelSizeY))   
    

    print ('Cell size: ',pixelSizeX,pixelSizeY,cellsize) 
    
    if refresh_sources:
        ### Extract shapefile by extent
        ogrcmd = """ogr2ogr -f "ESRI Shapefile" -nlt LINESTRING -explodecollections -spat %s %s %s %s "%s" "%s" """%(gt[0], gt[3] - pixelSizeY * raster.RasterYSize, gt[0] + pixelSizeX * raster.RasterXSize, gt[3],datadir,datadir+'/'+roadfile)
        print(ogrcmd)
        response=subprocess.check_output(ogrcmd, shell=True)
        sys.exit("Execution Halted")
        print (response) 
        # Extraction does not crop lines to bounding box, so reprocess using geopandas
        def bbox(long0, lat0, long1, lat1):
            return Polygon([[long0, lat0],
                            [long1,lat0],
                            [long1,lat1],
                            [long0, lat1]])
        clipframe = gp.GeoDataFrame(pd.DataFrame(['p1'], columns = ['geom']),
             crs = {'init':'epsg:27700'},
             geometry = [bbox(gt[0], gt[3] - pixelSizeY * raster.RasterYSize, gt[0] + pixelSizeX * raster.RasterXSize, gt[3])])
        roads = gp.read_file(datadir+'/'+shapefile_name)
        roads_clip = gp.clip(roads, clipframe, keep_geom_type=True)
        roads_clip = roads_clip[~roads_clip.is_empty]
        roads_clip.to_file(datadir+'/'+shapefile_name)
        
    del raster
    
    cross_sect_lines_shp = createPerpendLines(datadir+'/'+shapefile_name,crosssect_dist,crosssect_length)
    cross_sect_pts = cross_sect_lines_shp.replace('lines','points')
    interpolPointsAlongLines(cross_sect_lines_shp,cross_sect_pts,cellsize)        

    src_filename = mapfile
    shp_filename = cross_sect_pts
    src_ds=gdal.Open(src_filename) 
    gt=src_ds.GetGeoTransform()
    rb1=src_ds.GetRasterBand(1)
    rb2=src_ds.GetRasterBand(2)
    rb3=src_ds.GetRasterBand(3)
    
    ds=ogr.Open(shp_filename)
    lyr=ds.GetLayer()
    outdata = []
    counter=0
    allfeatcount = lyr.GetFeatureCount()
    for feat in lyr:
        counter+=1
        geom = feat.GetGeometryRef()
        mx,my=geom.GetX(), geom.GetY()  #coord in map units    
        #Convert from map to pixel coordinates.
        #Only works for geotransforms with no rotation.
        px = int((mx - gt[0]) / gt[1]) #x pixel
        py = int((my - gt[3]) / gt[5]) #y pixel
        
        try:
            intval1=rb1.ReadAsArray(px,py,1,1)[0]
            intval2=rb2.ReadAsArray(px,py,1,1)[0]
            intval3=rb3.ReadAsArray(px,py,1,1)[0]
        except:
            continue        
        outline = [mx,my,feat.GetFID(),feat.GetField('CHAINAGE'),feat.GetField('LINEFID'),intval1[0],intval2[0],intval3[0]]
        outdata.append(outline)
        #print (outline)
        print('collecting map color information per sampling location...',counter,'/',allfeatcount)    
    rgbvals_df = pd.DataFrame(outdata)
    rgbvals_df.columns = ['x','y','ptfid','chainage','linefid','r','g','b']  
    outcsv = datadir + os.sep + 'crossect.csv'
    rgbvals_df.to_csv(outcsv)    
    del ds,lyr
     
if calc_roi: ######################################################################################

    nanval=-32768 ### needs to be adjusted depending on the bitdepth of the scannes image
   
    incsv = datadir + os.sep + 'crossect.csv'
        
    rgbvals_df=pd.read_csv(incsv)    
    vector_proj_exploded_gdf=gp.read_file(filename=datadir + os.sep + shapefile_name)

    plot=False ### set to plot to see the axial images to console.
    linecount=0
    outdata_linestats=[]
    #line_total=rgbvals_df.linefid.unique().shape[0]
    line_total=rgbvals_df.linefid.unique().shape[0]
    for linefid,linefiddf in rgbvals_df.groupby('linefid'):

        linecount+=1
        chainage_count=0
        for chainage,chainagedf in linefiddf.groupby('chainage'):
            chainage_count+=1
            currlen=len(chainagedf)
            chainagedf=chainagedf.replace(nanval,np.nan)
            chainagedf=chainagedf.fillna(0)
            rgb_line = np.dstack((chainagedf.r.values,chainagedf.g.values,chainagedf.b.values))
            gray_line = np.mean(rgb_line,axis=2)
            
            ## Match Road Template
            if match_template:
                res = cv.matchTemplate(gray_line.astype(np.uint8),road_template.astype(np.uint8),4)
                min_val, max_val, min_loc, max_loc = cv.minMaxLoc(res)
                print ('Road Template Match: ',min_val)
                
            if chainage_count==1:
                rgb_band=rgb_line
                rtm_stack=np.array(min_val)
            else:
                try:
                    rgb_band=np.vstack((rgb_band,rgb_line))
                    rtm_stack=np.append(rtm_stack,min_val)
                except:
                    pass
        grayscale=np.mean(rgb_band,axis=2)
        #### trim bands that are longer than target_band_length:
        if grayscale.shape[0]>target_band_length:
            grayscale=grayscale[np.random.randint(0,grayscale.shape[0],target_band_length),:]                      
        target_band_width=int(crosssect_length/5.0)                                    
        padby_x=max(0,target_band_width-grayscale.shape[1])
        padby_y=max(0,target_band_length-grayscale.shape[0])
        
        padded=np.pad(grayscale, ((0,padby_y), (0, padby_x)), mode='reflect')  
        #print(padded.shape)
        lr_gradient=np.abs(np.diff(padded,axis=1,n=2))
        if plot:
            fig,ax=plt.subplots(2,2)
            ax[0,0].imshow(rgb_band)
            ax[0,1].imshow(padded)
            #lr_gradient=np.abs(np.diff(grayscale,axis=1,n=5,prepend=0,append=0))
            #lr_gradient=np.diff(padded,axis=1,n=2)
            ax[1,0].imshow(lr_gradient)
            ax[1,1].plot(np.sum(lr_gradient,axis=0))                       
            plt.show()
        crosssum=np.sum(lr_gradient,axis=0)
        #auc=np.sum(crosssum)
        roi_old=trapz(crosssum, np.arange(crosssum.shape[0]))
        roi=-np.mean(rtm_stack)
        outdata_linestats.append([linefid,roi,target_band_length,roi_old])
        print('calculating road overlap indicator...',crosssect_dist,crosssect_length,target_band_length,linecount,'/',line_total,roi,roi_old)
        
        #sys.exit(0)
    outdata_linestatsdf=pd.DataFrame(outdata_linestats,columns=['LINEFID','roi','target_band_length','roi_old'])
    vector_proj_exploded_gdf['LINEFID']=vector_proj_exploded_gdf.index
    vector_proj_exploded_gdf=vector_proj_exploded_gdf.merge(outdata_linestatsdf,on='LINEFID',how='right')

    print('clustering...')
    if DO_CKMEANS:
        X = vector_proj_exploded_gdf['roi'].values                                               
        clustered = ckmeans_lib.ckmeans(list(X),2)
        cluster_labels=np.zeros(X.shape)
        cluster_labels[np.in1d(X,clustered[1])]=1 
    else:
        X = vector_proj_exploded_gdf['roi'].values.reshape(-1, 1)                      
        clusterer = KMeans(n_clusters=3, random_state=0)                                        
        cluster_labels = clusterer.fit_predict(X) 
    
    print('exporting...')
    ### identify the "overlap" cluster (the one with higher avg ROI) and set it to label 1. ######
    vector_proj_exploded_gdf['cluster_labels']=cluster_labels              
    meandf= vector_proj_exploded_gdf.groupby('cluster_labels')['roi'].mean().reset_index()
    mean1=meandf[meandf.cluster_labels==1]['roi'].values[0]
    mean0=meandf[meandf.cluster_labels==0]['roi'].values[0]
    if mean0>mean1:
        ###swap
        vector_proj_exploded_gdf['cluster']=np.abs(cluster_labels-1) ## 0 to 1 and 1 to 0   
    vector_proj_exploded_outshp=datadir + os.sep + shapefile_name.replace('.shp','_w_roi_%s_%s.shp' %(crosssect_dist,crosssect_length))        
    vector_proj_exploded_gdf.to_file(filename=vector_proj_exploded_outshp)
    
if vis_roi:######################################################################################
    
    vector_proj_exploded = datadir + os.sep + shapefile_name        
    vector_proj_exploded_outshp=vector_proj_exploded.replace('.shp','_w_roi_%s_%s.shp' %(crosssect_dist,crosssect_length))
    gdf=gp.read_file(vector_proj_exploded_outshp)
    gdf['roi_pct']=gdf.roi.rank(pct=True)
    
    ### plot the ROI                      
    fig,ax=plt.subplots(figsize=(4,4))  
    ### plot
    col='roi_pct'
    cat=False
    k=20
    palette='turbo'
    plotdf = gdf.dropna(subset=[col],axis=0)                    
    plotdf.plot(ax=ax,column=col, categorical=cat,k=k, cmap=palette, legend=False,lw=1.0)# legend_kwds={'labels':}            
    ax.set_axis_off()  
    ax.set_facecolor("black")           
    plt.tight_layout()
    fig.set_facecolor('black')
    fig.savefig(datadir+os.sep+'roadsegments_roi_%s_%s_%s' %(crosssect_length,crosssect_dist,target_band_length),dpi=150,bb_inches='tight')                        

    ### plot the historical roads
    fig,ax=plt.subplots(figsize=(4,4))                      
    ### plot
    col='cluster'
    cat=True
    k=2
    palette='viridis'
    plotdf = gdf.dropna(subset=[col],axis=0)                    
    plotdf.plot(ax=ax,column=col, categorical=cat,k=k, cmap=palette, legend=False,lw=1.0)# legend_kwds={'labels':}            
    ax.set_axis_off()  
    ax.set_facecolor("black")          
    plt.tight_layout()
    fig.set_facecolor('black')
    fig.savefig(datadir+os.sep+'roadsegments_clusters_%s_%s_%s' %(crosssect_length,crosssect_dist,target_band_length),dpi=150,bb_inches='tight')                        
    plt.show()                 
    
    
        
        