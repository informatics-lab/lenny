import iris
import matplotlib.pyplot as plt
import matplotlib.cm as mpl_cm
import iris.quickplot as qplt
import iris.plot as iplt
from mpl_toolkits import mplot3d
import numpy as np
from iris.experimental.equalise_cubes import equalise_attributes
import iris.plot as iplot
import iris.analysis.cartography
from matplotlib.transforms import offset_copy
import cartopy.crs as ccrs
import cartopy.io.img_tiles as cimgt
import os
from iris.cube import CubeList
from dask import delayed
import dask.bag as db
from distributed import Client
from matplotlib.widgets import Slider
import ffmpeg
import subprocess
import matplotlib.font_manager as fm
import matplotlib.colors as colors
from dask_kubernetes import KubeCluster
import matplotlib
from matplotlib.ft2font import FT2Font

"""
Recommended that requirements.txt is installed before installing this library. Download, cd to its directory and type 'pip install -r requirements.txt' into shell.
"""

client = Client()

def load_path(folder_path):
    filenames = os.listdir(folder_path)
    filepaths = [os.path.join(folder_path, file) for file in filenames]
    return filepaths
    
def __load_uniform_cubes_from_filepath__(filepath, add_coord=None, aggregate=None, subset=None, masking=None):
    """
    Load cubes with uniform measurements from path to CF NetCDF, GRIB 1 & 2, PP and FieldsFiles files. Returns a list of processed cubes.
    Arguments:
    filepath: Filepath to data. Will attempt to read everything within this filepath.
    add_coord: Turns a metadata attribute into a new cube dimension. Takes a tuple in this format - (meta_data_name, starting_index, final_index, new_dimension_name). meta_data_name=string value of attribute, starting_index=index of starting numerical value in attribute to be contained in new dimension, final_index=end index of numerical value in attribute to be contained in new dimension, new_dimension_name=string value, name of new cube dimension.
    aggregate: Takes dimension to collapse cube along and returns cumulative sum of coordinate along that dimension. Collapses cube dimensions if cube has more than 2 dimensions. Dimension must contain non-uniform data.
    subset: Restricts data to intersection of cube with specified coordinate ranges. Takes a tuple in this format - (west, east, south, north).
    masking: Masks all data that are smaller than a specified value. Takes a float.
    """
    
    cubelist = iris.load(filepath)
#may not work if don't add add_coord?
    if type(cubelist) == iris.cube.CubeList:
        if add_coord == None:
            for c in cubelist:
                c.rename('variable_name_for_merge')
                    
        if type(add_coord) == tuple:
            meta_data_name, starting_index, final_index, new_dimension_name = add_coord
            for c in cubelist:
                c.rename('variable_name_for_merge')
                n = int(c.attributes[meta_data_name][starting_index:final_index])
                c.add_aux_coord(iris.coords.AuxCoord(n, new_dimension_name))
    
    equalise_attributes(cubelist)
        
    cubelist = cubelist.merge_cube()
            
    if subset==None:
        subset = cubelist[0]
    if type(subset) == tuple:
        west, east, south, north = subset
        subset = cubelist[0].intersection(longitude=(west,east), latitude=(south,north))
        
    if type(cubelist) == iris.cube.Cube:
        if subset==None:
            subset = cubelist
        if type(subset) == tuple:
            west, east, south, north = subset
            subset = cubelist.intersection(longitude=(west,east), latitude=(south,north))
                
    if type(aggregate) == str:
        cubelist = cubelist.collapsed(aggregate, iris.analysis.SUM)
            
    if masking==None:
        subset = subset
    if type(masking)==float:
        subset.data = np.ma.masked_where(subset.data <= masking, subset.data)
        
    #processed_cube_list.append(subset)
    
    return subset

def load_uniform_cubes_from_filepath(listoffilepath, add_coord=None, aggregate=None, subset=None, masking=None, scheduler_address=None):
    if scheduler_address is not None:
        client =  Client(scheduler_address)
        lazycubes = db.from_sequence(listoffilepath).map(__load_uniform_cubes_from_filepath__)
        lazycubes = lazycubes.compute()
    if scheduler_address==None:
        lazycubes = db.from_sequence(listoffilepath).map(__load_uniform_cubes_from_filepath__)
    #cubes = loadcubes.compute()
    return lazycubes

def __extract_cube_from_filepath__(filepath, constraint):
    """
    Extract a single cube from a cubelist extracted from path to CF NetCDF, GRIB 1 & 2, PP and FieldsFiles files.
    loaded_path: Path to the file containing the cubelist.
    constraint: a string, float, or interger describing a property of the cube (e.g. name, model level number, etc...) that distinguishes it from other cubes in the cubelist.
    Example: ('./prods_op_mogreps-uk_20130703_03_00_003.nc','stratiform_snowfall_rate')
    """
    
    cube = iris.load_cube(filepath, constraint)
    
    return cube

def extract_cube_from_filepath(filepath, constraint):
    loadcubes = db.from_sequence(filepaths).map(__extract_cube_from_filepath__)
    cubes = loadcubes.compute()
        
def __make_plots_from_cubes__(cube_list, save_filepath, figsize=(16,9), logscaled=True, vmin=None, vmax=None, colourmap='viridis', colourbarticks=None, colourbarticklabels=None, colourbar_label=None, markerpoint=None, markercolor='#B9DC0C', timestamp=None, plottitle=None, box_colour='#FFFFFF'):
    """
    Make plots from list of processed cube.
    Arguments:
    cube_list: Takes list of cubes.
    figsize: Sets size of figure. Default is 16 in x 9 in. Takes a tuple (e.g. (16, 9)).
    logscaled: Normalises Data on a logarithm (to the base-10) scale. Takes Boolean value (True or False). Default is True.
    vmin = set smallest value - float.
    vmax = set largest value - float.
    colourmap: Sets colour map for the plot. Default is 'viridis'. Other colourmaps: 'magma', 'plasma', 'inferno', 'cividis'. See https://matplotlib.org/tutorials/colors/colormaps.html for more colourmap options.
    colourbarticks: Sets position of ticks on colourbar. Takes a list of floats or integers, e.g. [10, 100, 1000].
    colourbarticklabels: Sets labels for colourbar ticks. Takes a list.
    colourbar_label: Sets colourbar legend. Takes a string.
    markerpoint: Plots a marker on the map based on global coordinates. Takes a tuple in this format - (longitude, latitude, name_of_place), longitude and latitude must be a float, name_of_place must be a string.
    markercolor: Color of the location marker. Must be given as a string. Default is '#B9DC0C'.
    timestamp: Places a timestamp box on the map. Must contain timesteps in original metadata, as this takes the name of the timestep attribute.
    plottitle: Displays the title of your video across the top. Takes string.
    
    """

    sequence=list(enumerate(cube_list))
    for cubetuple in sequence:
        cubenumber, cube = cubetuple
        
        if figsize == False:
            fig, ax = plt.subplots(figsize=(16,9))
        if type(figsize) == tuple:
            fig, ax = plt.subplots(figsize=figsize)
    
        terrain = cimgt.Terrain()
        fig = plt.axes(projection=terrain.crs)
        fig.add_image(terrain, 4)
    
        if logscaled==True and vmin==None and vmax==None and colourmap == 'viridis':
            data = iplt.pcolormesh(cube, alpha=1, norm=colors.LogNorm(), cmap='viridis')
        
        if logscaled==True and type(vmin) == float and type(vmax) == float and colourmap == 'viridis':
            data = iplt.pcolormesh(cube, alpha=1, norm=colors.LogNorm(vmin=vmin, vmax=vmax), cmap='viridis')
    
        if logscaled==True and vmin==None and vmax==None and type(colourmap)==str:
            data = iplt.pcolormesh(cube, alpha=1, norm=colors.LogNorm(), cmap=colourmap)
        
        if logscaled==True and type(vmin) == float and type(vmax) == float and type(colourmap)==str:
            data = iplt.pcolormesh(cube, alpha=1, norm=colors.LogNorm(vmin=vmin, vmax=vmax), cmap=colourmap)
        
        if logscaled==False and vmin==None and vmax==None and colourmap == 'viridis':
            data = iplt.pcolormesh(cube, alpha=1, norm=colors.LogNorm(), cmap='viridis')
        
        if logscaled==False and type(vmin) == float and type(vmax) == float and colourmap == 'viridis':
            data = iplt.pcolormesh(cube, alpha=1, vmin=vmin, vmax=vmax, cmap='viridis')
    
        if logscaled==False and vmin==None and vmax==None and type(colourmap)==str:
            data = iplt.pcolormesh(cube, alpha=1, cmap=colourmap)
        
        if logscaled==False and type(vmin) == float and type(vmax) == float and type(colourmap)==str:
            data = iplt.pcolormesh(cube, alpha=1, vmin=vmin, vmax=vmax, cmap=colourmap)
    
        if coastlines==True:
            plt.gca().coastlines('50m')
    
        cbaxes = plt.axes([0.2, 0.25, 0.65, 0.03])
        colorbar = plt.colorbar(data, cax=cbaxes, orientation = 'horizontal')
        colorbar.set_ticks(colorbarticks)
        colorbar.set_ticklabels(colorbarticklabels)
    
        colorbar.set_label(colourbar_label, fontproperties='FT2Font', color=box_colour, fontsize=8, bbox=dict(facecolor=box_colour, edgecolor='#2A2A2A', boxstyle='square'))
    
        if markerpoint is not None and markercolor is not None:
            longitude, latitude, name_of_place = markerpoint
            fig.plot(longitude, latitude, marker='^', color=markercolor, markersize=12, transform=ccrs.Geodetic())
            geodetic_transform = ccrs.Geodetic()._as_mpl_transform(fig)
            text_transform = offset_copy(geodetic_transform, units='dots', y=+75)
            fig.text(longitude, latitude, name_of_place, fontproperties='FT2Font', alpha=1, fontsize=8, verticalalignment='center', horizontalalignment='right', transform=text_transform, bbox=dict(facecolor=markercolor, edgecolor='#2A2A2A', boxstyle='round'))
    
        if timestamp is not None:
            attributedict = subset.attributes
            datetime = attributedict.get(timestamp)
            timetransform = offset_copy(geodetic_transform, units='dots', y=0)
            longitude_of_time_box, latitude_of_time_box = time_box_position
            fig.text(longitude_of_time_box, latitude_of_time_box, "Time, date: "+ datetime, fontproperties='FT2Font', alpha=0.7, fontsize=8 , transform=timetransform, bbox=dict(facecolor=markercolor, edgecolor='#2A2A2A', boxstyle='round'))
    
        titleaxes = plt.axes([0.2, 0.8, 0.65, 0.04], facecolor=box_colour)
        titleaxes.text(0.5,0.25, plottitle, horizontalalignment = 'center',  fontproperties='FT2Font', fontsize=10, weight=600, color = textcolor)
        titleaxes.set_yticks([])
        titleaxes.set_xticks([])

    
        picturename = save_filepath + "%04i.png" % cubenumber
        plt.savefig(picturename, dpi=200, bbox_inches="tight")

def make_plots_from_cubes(cube_list, save_filepath, figsize=(16,9), logscaled=True, vmin=None, vmax=None, colourmap='viridis', colourbarticks=None, colourbarticklabels=None, colourbar_label=None, markerpoint=None, markercolor='#B9DC0C', timestamp=None, plottitle=None, box_colour='#FFFFFF'):
    makingplots = db.from_sequence(cube_list).map(__make_plots_from_cubes__)
    plots = makingplots.compute()
    
def make_video(picture_filepath, end_video_filepath, interpolate=False):
    """
    picture_filepath: Filepath to plots to be video frames.
    end_video_filepath: Intended filepath and filename of video.
    interpolate: creates additional frames between existing, meaning goes from 24 to 60 fps. This is done by mean of the adjacent frames. Takes bool.
    In order to use interpolate, must have ffmpeg 3.1 installed or higher. If you're video is over (N) bytes, call pretty_weather.resize_video('video') to decrease bytes.
    """
    
    if interpolate==False:
        return_value = subprocess.call(["ffmpeg","-y","-r","24", "-i", (picture_filepath + "/%04d.png"), "-vcodec", "mpeg4","-qscale","5", "-r", "24", end_video_filepath])
        return return_value
    
    if interpolate==True:
        return_value = subprocess.call(["ffmpeg","-y","-r","24", "-i", (picture_filepath + "/%04d.png"), "-filter", "minterpolate", "-vcodec", "mpeg4","-qscale","5", "-r", "24", end_video_filepath])
    return return_value
    make_video(end_video_filepath, picture_filepath, *kwargs)
    
def resize_video(video_filepath, end_video_filepath):
        clip = mp.VideoFileClip(video_filepath)
        clip_resized = clip.resize(height=1000)
        clip_resized.write_videofile(end_video_filepath)
    
if __name__ == "__main__":
    import sys
    fib(int(sys.argv[1]))