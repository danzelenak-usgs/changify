"""
ARD related functionality
"""
import os
from collections import namedtuple
from functools import partial
from itertools import chain
from typing import Union, NamedTuple, Tuple

from osgeo import gdal
import merlin

from changify.app import Config


# Typing Jazz
Num = Union[float, int]


class GeoExtent(NamedTuple):
    """
    Simple container to organize projected spatial extent parameters.
    """
    xmin: Num
    ymax: Num
    xmax: Num
    ymin: Num


class GeoCoordinate(NamedTuple):
    """
    Simple container to keep a projected coordinate pair together.
    """
    x: Num
    y: Num


class RowColumn(NamedTuple):
    """
    Simple container to keep a row/column pair together.
    """
    row: int
    column: int


class RowColumnExtent(NamedTuple):
    """
    Simple container to organize row/column extent parameters.
    """
    st_row: int
    st_col: int
    end_row: int
    end_col: int


# Defined Extents for the ARD data sets
ARDCONUS_EXT = GeoExtent(-2565585, 3314805, 2384415, 14805)
ARDAK_EXT = GeoExtent(-851715, 2474325, 1698285, 374325)
ARDHI_EXT = GeoExtent(-444345, 2168895, 305655, 1718895)

# Defined Affines to help with Transformations
ARDCONUS_CHIPAFF = (ARDCONUS_EXT[0], 3000, 0, ARDCONUS_EXT[1], 0, -3000)

ARDCONUS_TILEAFF = (ARDCONUS_EXT[0], 15e4, 0, ARDCONUS_EXT[1], 0, -15e4)


def create(x: Num, y: Num, acquired: str):
    h, v = determine_hv(GeoCoordinate(x, y))
    pass


def ard_hv(h: int, v: int, extent: GeoExtent=ARDCONUS_EXT) -> Tuple[GeoExtent, tuple]:
    """
    Geospatial extent and 30m affine for a given ARD grid location.

    Args:
        h (int): horizontal grid number
        v (int): vertical grid number
        extent (sequence): ARD reference extent

    Returns:
        GeoExtent and GeoAffine namedtuples

    Examples:
        >>> ext, aff = ard_hv(5, 2)
        >>> ext
        GeoExtent(xmin=-1815585, ymax=3014805, xmax=-1665585, ymin=2864805)
        >>> aff
        GeoAffine(ulx=-1815585, xres=30, rot1=0, uly=3014805, rot2=0, yres=-30)
    """
    # Spelled out for clarity
    xmin = extent[0] + h * 5000 * 30
    xmax = extent[0] + h * 5000 * 30 + 5000 * 30
    ymax = extent[1] - v * 5000 * 30
    ymin = extent[1] - v * 5000 * 30 - 5000 * 30

    return (GeoExtent(xmin, ymax, xmax, ymin),
            (xmin, 30, 0, ymax, 0, -30))


def fifteen_offset(val: Num) -> int:
    """
    Aligns a given coordinate with nearest value that is a multiple of 15 and
    an odd number. Used for aligning the upper left of a given pixel to the
    USGS standard 30 meter grid.

    Args:
        val: value to adjust

    Returns:
        int

    Examples:
        >>> fifteen_offset(1)
        15
        >>> fifteen_offset(-1)
        -15
        >>> fifteen_offset(0)
        15
        >>> fifteen_offset(0.1)
        15
    """
    return int(val // 30) * 30 + 15


def transform_geo(coord: GeoCoordinate, affine: tuple) -> RowColumn:
    """
    Perform the affine transformation from a geospatial coordinate to row/col
    space.

    This function assumes that you are seeking the row and column of the pixel
    that the spatial coordinate falls in, for a given affine.

    Yline = (Ygeo - GT(3) - Xpixel*GT(4)) / GT(5)
    Xpixel = (Xgeo - GT(0) - Yline*GT(2)) / GT(1)

    From:
    http://www.gdal.org/gdal_datamodel.html

    Args:
        coord (sequence): (x, y) coordinate pair
        affine (sequence): transformation tuple

    Returns:
        RowColumn namedtuple

    Examples:
        >>> ext, aff = ard_hv(5, 2)
        >>> aff
        GeoAffine(ulx=-1815585, xres=30, rot1=0, uly=3014805, rot2=0, yres=-30)
        >>> coord = GeoCoordinate(-1767039, 2940090)
        >>> rowcol = transform_geo(coord, aff)
        >>> rowcol
        RowColumn(row=2490, column=1618)
        >>> xy = transform_rc(rowcol, aff)
        >>> xy
        GeoCoordinate(x=-1767045, y=2940105)
    """
    # Spelled out for clarity
    col = (coord[0] - affine[0] - affine[3] * affine[2]) / affine[1]
    row = (coord[1] - affine[3] - affine[0] * affine[4]) / affine[5]

    return RowColumn(int(row), int(col))


def transform_rc(rowcol: RowColumn, affine: tuple) -> GeoCoordinate:
    """
    Perform the affine transformation from a row/col coordinate to a geospatial
    space.

    Pixel being defined by the upper left.

    Xgeo = GT(0) + Xpixel*GT(1) + Yline*GT(2)
    Ygeo = GT(3) + Xpixel*GT(4) + Yline*GT(5)

    From:
    http://www.gdal.org/gdal_datamodel.html

    Args:
        rowcol (sequence): (row, column) pair
        affine (sequence): transformation tuple

    Returns:
        GeoCoordinate namedtuple

    Examples:
        >>> ext, aff = ard_hv(5, 2)
        >>> aff
        GeoAffine(ulx=-1815585, xres=30, rot1=0, uly=3014805, rot2=0, yres=-30)
        >>> coord = GeoCoordinate(-1767039, 2940090)
        >>> rowcol = transform_geo(coord, aff)
        >>> rowcol
        RowColumn(row=2490, column=1618)
        >>> xy = transform_rc(rowcol, aff)
        >>> xy
        GeoCoordinate(x=-1767045, y=2940105)
    """
    # Spelled out for clarity
    x = affine[0] + rowcol[1] * affine[1] + rowcol[0] * affine[2]
    y = affine[3] + rowcol[1] * affine[4] + rowcol[0] * affine[5]

    return GeoCoordinate(x, y)


def split_extent(extent):
    """
    Helper func

    Splits an extent into it's UL and LR
    """
    if isinstance(extent, GeoExtent):
        t = GeoCoordinate
    elif isinstance(extent, RowColumnExtent):
        t = RowColumn
    else:
        raise TypeError

    return t(extent[0], extent[1]), t(extent[2], extent[3])


def transform_ext(extent, affine):
    """

    """
    if isinstance(extent, GeoExtent):
        t = RowColumnExtent
        map_func = partial(transform_geo, affine=affine)
    elif isinstance(extent, RowColumnExtent):
        t = GeoExtent
        map_func = partial(transform_rc, affine=affine)
    else:
        raise TypeError

    return t(*chain(*map(map_func, split_extent(extent))))


def determine_hv(coord: GeoCoordinate, aff: tuple=ARDCONUS_TILEAFF) -> Tuple[int, int]:
    """
    Determine the ARD tile H/V that contains the given coordinate.

    The 'H' corresponds to the column, and the 'V' corresponds to the row, so
    we can use a normal affine transformation. But because of normal usage, the
    'H' typically comes first.

    Args:
        coord (sequence): (x, y) coordinate pair
        aff:

    Returns:
        tuple, (h, v)
    """
    return transform_geo(coord, aff)[::-1]


def open_raster(path: str, readonly: bool=True):
    if readonly:
        return gdal.Open(path, gdal.GA_ReadOnly)
    else:
        return gdal.Open(path, gdal.GA_Update)


def raster_extent(path: str) -> GeoExtent:
    ds = open_raster(path)

    affine = raster_affine(path)
    rc_lr = RowColumn(ds.RasterYSize, ds.RasterXSize)

    geo_lr = transform_rc(rc_lr, affine)

    return GeoExtent(xmin=affine[0], xmax=geo_lr.x,
                     ymin=geo_lr.y, ymax=affine[3])


def raster_affine(path: str) -> tuple:
    """
    Retrieve the affine/GeoTransform from a raster
    """
    ds = open_raster(path)

    return ds.GetGeoTransform()


def raster_band(path: str, band: int=1):
    ds = open_raster(path)

    return ds.GetRasterBand(band).ReadAsArray()


def extract_geoextent(path: str, geo_extent: GeoExtent, band: int=1):
    affine = raster_affine(path)
    rc_ext = transform_ext(geo_extent, affine)

    return extract_rcextent(path, rc_ext, band)


def extract_rcextent(path: str, rc_extent: RowColumnExtent, band: int=1):
    ds = open_raster(path)

    ul, lr = split_extent(rc_extent)

    return ds.GetRasterBand(band).ReadAsArray(ul.column,
                                              ul.row,
                                              lr.column - ul.column,
                                              lr.row - ul.row)


def chipul(coord: GeoCoordinate, aff: tuple=ARDCONUS_CHIPAFF) -> GeoCoordinate:
    """
    Chip defined as a 100x100 30m pixel area.

    Args:
        coord (sequence): (x, y) coordinate pair
        aff:

    Returns:

    """
    # Flip it!
    rc = transform_geo(coord, aff)
    return transform_rc(rc, aff)


def extract_chip(path: str, coord: GeoCoordinate, band: int=1):
    """
    Chip defined as a 100x100 30m pixel area.

    Args:
        path:
        coord (sequence): (x, y) coordinate pair
        band:

    Returns:

    """
    chip_ul = chipul(coord)
    chip_ext = GeoExtent(chip_ul[0], chip_ul[1], chip_ul[0] + 3000, chip_ul[1] - 3000)

    return extract_geoextent(path, chip_ext, band)
