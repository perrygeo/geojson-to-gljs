#!/usr/bin/env python
# pylint: disable=E1120
import click
import cligj
import json
import os

from jinja2 import Template
from shapely.geometry import asShape
from jenks import jenks

from colorbrewer import colors


template = Template(open("template.html").read())


def _set_precision(coords, precision):
    result = []
    try:
        return round(coords, int(precision))
    except TypeError:
        for coord in coords:
            result.append(_set_precision(coord, precision))
    return result


def process_factory(precision=6, drop=None):
    if not drop:
        drop = tuple()

    def func(f):
        newf = f.copy()
        coords = _set_precision(f['geometry']['coordinates'], precision)
        newf['geometry']['coordinates'] = coords
        newf['properties'] = {}
        for key, value in f['properties'].items():
            if key not in drop and value is not None:
                newf['properties'][key] = value
        return newf

    return func


def calc_stops(vals, ramp, nodata=-99):
    vals = [v for v in vals if v != nodata]
    try:
        _ramps = colors[ramp]
    except KeyError:
        raise KeyError("ramp must be one of {}".format(', '.join(colors.keys())))

    n_classes = 8
    _colors = _ramps[n_classes]

    try:
        float(vals[0])
        _breaks = [float(x) for x in jenks(vals, n_classes)]
        _stops = list(zip(_breaks, _colors))
    except ValueError:
        uniq = list(zip(set(vals)))
        # Try for ramp of exact length
        try:
            _colors = _ramps[n_classes]
        except KeyError:
            pass
        # Broadcast colors in cycle
        while len(_colors) < len(uniq):
            _colors += _colors

        _stops = list(zip(set(vals), _colors))

    return _stops


def constrain_bounds(bounds):
    newbounds = bounds[:]
    newbounds[0] = bounds[0] if bounds[0] >= -180 else -180
    newbounds[1] = bounds[1] if bounds[1] >= -85 else -85
    newbounds[2] = bounds[2] if bounds[2] <= 180 else 180
    newbounds[3] = bounds[3] if bounds[3] <= 85 else 85
    return newbounds

def expand_bounds(bounds, newbounds):
    if newbounds[0] < bounds[0]:
        bounds[0] = newbounds[0]
    if newbounds[1] < bounds[1]:
        bounds[1] = newbounds[1]
    if newbounds[2] > bounds[2]:
        bounds[2] = newbounds[2]
    if newbounds[3] > bounds[3]:
        bounds[3] = newbounds[3]
    return bounds

@click.command()
@cligj.features_in_arg
@click.option('--precision', type=int, help="number of decimal places", default=6)
@click.option('--token', type=str, default=None)
@click.option('--title', type=str, default='')
@click.option('--label', type=str, default=None)
@click.option('--categorical', is_flag=True, type=str, default=False)
@click.option('--radius', type=str, default=None,
              help="Property to use as the circle color")
@click.option('--color', type=str, default=None,
              help="Property to use as the color")
@click.option('--ramp', type=str, default="YlGnBu")
def main(features, categorical, precision, title, token, label, radius, color, ramp):
    proc = process_factory(precision)
    token = token or os.environ.get("MAPBOX_PUBLIC_TOKEN")
    # TODO external vs embed
    # TODO radius and radius legend
    # TODO labels
    # TODO hover style
    # TODO click handler?
    # TODO categorical flag for numeric data
    # TODO sort order for categories
    polys = []
    points = []
    lines = []
    color_vals = []
    radius_vals = []
    bounds = [180, 90, -180, -90]
    props = set()
    # TODO check if raw color or raw radius
    color_prop = color
    radius_prop = radius
    for feature in features:
        shape = asShape(feature['geometry'])
        bounds = expand_bounds(bounds, shape.bounds)
        if 'Line' in feature['geometry']['type']:
            lines.append(proc(feature))
        elif 'Polygon' in feature['geometry']['type']:
            polys.append(proc(feature))
        elif 'Point' in feature['geometry']['type']:
            points.append(proc(feature))

        if radius_prop:
            val = feature['properties'].get(radius_prop, None)
            if val:
                radius_vals.append(val)

        if color_prop:
            val = feature['properties'].get(color_prop, None)
            if val:
                color_vals.append(val)

        [props.add(k) for k in feature['properties'].keys()]

    props = sorted(props)

    color = '"#00f"'  # TODO default
    legend = ""
    if color_prop:
        stops = calc_stops(color_vals, ramp)

        # TODO do this in template.html
        precision = 4
        legend = "<table><tr><th></th><th style='text-align:left'>{}</th></tr>".format(color_prop)
        for b in stops:
            try:
                txt = round(b[0], precision)
            except TypeError:
                txt = b[0]
            legend += "<tr><th style='background-color:{};width:80px;'>&nbsp;</th><td>{}</td></tr>".format(b[1], txt)
        legend += "</table>"

        if isinstance(stops[0][0], str) or categorical:
            lookup = {None: None}
            for i, brk in enumerate(stops):
                stops[i] = (i, stops[i][1])
                lookup[brk[0]] = i

            _polys = []
            for f in polys:
                f['properties']['__category__'] = lookup[f['properties'].get(color_prop)]
                _polys.append(f)
            polys = _polys

            _lines = []
            for f in lines:
                f['properties']['__category__'] = lookup[f['properties'].get(color_prop)]
                _lines.append(f)
            lines = _lines

            _points = []
            for f in points:
                f['properties']['__category__'] = lookup[f['properties'].get(color_prop)]
                _points.append(f)
            points = _points

            color_prop = "__category__"

        color = json.dumps({
            'property': color_prop,
            'stops': stops})

    # TODO default radius
    radius = 5
    if radius_prop:
        nodata = -99  # todo
        radius_vals = [r for r in radius_vals if r != nodata]
        low = min(radius_vals)
        high = max(radius_vals)
        if isinstance(low, str):
            raise ValueError("radius property must be numeric")
        r = {
            "property": radius_prop,
            "base": 1.8,
            "stops": [
                [{'zoom': 0, 'value': low}, 4],
                [{'zoom': 0, 'value': high}, 20],
                [{'zoom': 20, 'value': low}, 400],
                [{'zoom': 20, 'value': high}, 2000]]}
        radius = json.dumps(r)

        # TODO do this in template.html
        precision = 4
        legend += "<br><table><tr><th></th><th style='text-align:left'>{}</th></tr>".format(radius_prop)
        legend += '<tr><th width="80"><svg width="42" height="42"><circle cx="21" cy="21" r="4" style="stroke:#006600; fill:none"></circle></svg></th><td>{}</td></tr>'.format(low)
        legend += '<tr><th width="80"><svg width="42" height="42"><circle cx="21" cy="21" r="20" style="stroke:#006600; fill:none"></circle></svg></th><td>{}</td></tr>'.format(high)
        legend += "</table>"

    if not token:
        raise click.UsageError("Must specify --token or set MAPBOX_PUBLIC_TOKEN")

    bounds = constrain_bounds(bounds)

    html = template.render(
        points=',\n'.join(json.dumps(f) for f in points),
        lines=',\n'.join(json.dumps(f) for f in lines),
        polys=',\n'.join(json.dumps(f) for f in polys),
            minll=json.dumps(bounds[:2]),
        maxll=json.dumps(bounds[2:]),
        title=title,
        color=color,
        legend=legend,
        radius=radius,
        props=json.dumps(props),
        token=token)

    click.echo(html)


if __name__ == "__main__":
    main()
