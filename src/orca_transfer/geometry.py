"""Read-only, conservative fit checks for editable 3MF meshes and components."""
from __future__ import annotations

import math
import posixpath
import xml.etree.ElementTree as ET


class GeometryError(ValueError):
    pass


def xml_document(data: bytes):
    # Reject DTDs and entity declarations, including UTF-16/32 spellings.
    if b'<!DOCTYPE' in data.replace(b'\x00', b'').upper() or b'<!ENTITY' in data.replace(b'\x00', b'').upper():
        raise GeometryError('XML entities and document types are unsupported.')
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise GeometryError('Malformed XML in project metadata or geometry.') from exc


def local_name(tag):
    return tag.rsplit('}', 1)[-1]


def number(value):
    try:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError()
        return value
    except (TypeError, ValueError) as exc:
        raise GeometryError('Geometry and build dimensions must contain finite numbers.') from exc


def polygon(value):
    if not isinstance(value, list) or len(value) < 3:
        raise GeometryError('The target profile needs a valid printable_area polygon.')
    result = []
    for point in value:
        parts = str(point).lower().replace(',', 'x').split('x')
        if len(parts) != 2:
            raise GeometryError('Unsupported printable_area coordinate format.')
        result.append(tuple(number(x) for x in parts))
    if abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(result, result[1:] + result[:1]))) < 1e-8:
        raise GeometryError('The target printable area has zero area.')
    return result


def convex(poly):
    signs = set()
    for a, b, c in zip(poly, poly[1:]+poly[:1], poly[2:]+poly[:2]):
        turn = (b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0])
        if abs(turn) > 1e-8:
            signs.add(turn > 0)
    # Also reject self-intersecting polygons: all vertices must lie on the same
    # side of every edge. This catches star polygons with same-sign local turns.
    for a,b in zip(poly, poly[1:]+poly[:1]):
        sides = {(b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]) > 0
                 for p in poly if abs((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])) > 1e-8}
        if len(sides) > 1:
            return False
    return len(signs) == 1


def inside(point, poly):
    x, y = point
    hit = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        cross = (x-a[0])*(b[1]-a[1]) - (y-a[1])*(b[0]-a[0])
        if abs(cross) < 1e-5 and min(a[0], b[0])-1e-5 <= x <= max(a[0], b[0])+1e-5 and min(a[1], b[1])-1e-5 <= y <= max(a[1], b[1])+1e-5:
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            hit = not hit
    return hit


def matrix(value):
    result = [number(x) for x in value.split()] if value else [1,0,0,0,1,0,0,0,1,0,0,0]
    if len(result) != 12:
        raise GeometryError('Unsupported 3MF transform; expected twelve numbers.')
    return result


def transform(point, mat):
    x, y, z = point
    return tuple(x*mat[i] + y*mat[i+3] + z*mat[i+6] + mat[i+9] for i in range(3))


def check_fit(archive, entries, settings):
    """Validate placed object bounding rectangles; never alter model bytes.

    Bounding rectangles are intentionally conservative for circular/concave beds
    and exclude zones. Modifiers are included; complex layouts may need manual
    transfer instead. No claim about supports, brims or toolpath clearance.
    """
    bed = polygon(settings.get('printable_area'))
    if not convex(bed):
        raise GeometryError('Concave or self-intersecting build plates need manual placement validation in Orca; this version supports convex printable areas.')
    height = number(settings.get('printable_height'))
    if height <= 0:
        raise GeometryError('The target profile needs a positive printable height.')
    exclusions = settings.get('bed_exclude_area', [])
    excluded = polygon(exclusions) if exclusions and any(str(x) not in ('0x0', '0,0') for x in exclusions) else []
    documents = {}
    objects = {}
    for name, info in entries.items():
        if not name.endswith('.model'):
            continue
        if info.file_size > 128 * 1024 * 1024:
            raise GeometryError('A model XML exceeds the 128 MB inspection limit.')
        root = xml_document(archive.read(info))
        if root.get('unit', 'millimeter') != 'millimeter':
            raise GeometryError('Only millimeter 3MF projects are supported; save in Orca first.')
        documents[name] = root
        for resource in root:
            if local_name(resource.tag) == 'resources':
                for obj in resource:
                    if local_name(obj.tag) == 'object':
                        key = (name, obj.get('id'))
                        if key in objects:
                            raise GeometryError('Duplicate 3MF object identity.')
                        objects[key] = obj

    def vertices(path, identifier, transforms, visiting):
        key = (path, identifier)
        if key in visiting or len(visiting) > 64:
            raise GeometryError('Cyclic or excessively nested 3MF components.')
        obj = objects.get(key)
        if obj is None:
            raise GeometryError('A 3MF component references a missing object.')
        visiting = visiting | {key}
        for child in obj:
            kind = local_name(child.tag)
            if kind == 'mesh':
                for container in child:
                    if local_name(container.tag) == 'vertices':
                        for vertex in container:
                            p = tuple(number(vertex.get(axis)) for axis in ('x','y','z'))
                            for mat in transforms:
                                p = transform(p, mat)
                            yield p
            elif kind == 'components':
                for component in child:
                    reference = next((v for k, v in component.attrib.items() if local_name(k) == 'path'), '')
                    other = path
                    if reference:
                        if '\\' in reference or ':' in reference:
                            raise GeometryError('Unsupported external 3MF component reference.')
                        other = (reference.lstrip('/') if reference.startswith('/') else
                                 posixpath.normpath(posixpath.join(posixpath.dirname(path), reference))).casefold()
                        if other.startswith('../'):
                            raise GeometryError('A component reference leaves the project archive.')
                    yield from vertices(other, component.get('objectid'), [matrix(component.get('transform')), *transforms], visiting)

    main = documents.get('3d/3dmodel.model')
    if main is None:
        raise GeometryError('No root 3MF model found.')
    placed = 0
    for build in main:
        if local_name(build.tag) != 'build':
            continue
        for item in build:
            if local_name(item.tag) != 'item' or item.get('printable', '1') in ('0', 'false'):
                continue
            bounds = [math.inf, math.inf, math.inf, -math.inf, -math.inf, -math.inf]
            for p in vertices('3d/3dmodel.model', item.get('objectid'), [matrix(item.get('transform'))], set()):
                for i in range(3):
                    bounds[i] = min(bounds[i], p[i])
                    bounds[i+3] = max(bounds[i+3], p[i])
            if not math.isfinite(bounds[0]):
                raise GeometryError('An editable build object contains no mesh vertices.')
            placed += 1
            x0, y0, z0, x1, y1, z1 = bounds
            corners = [(x0,y0), (x1,y0), (x1,y1), (x0,y1)]
            # Reject beds with a concave notch inside the object's rectangle too.
            notch = any(x0+1e-5 < x < x1-1e-5 and y0+1e-5 < y < y1-1e-5 for x,y in bed)
            if z0 < -0.05 or z1 > height+1e-5 or notch or not all(inside(p, bed) for p in corners):
                raise GeometryError('A placed object or modifier does not fit the target build volume. Reposition/resize it in Orca; this tool preserves placement.')
            if excluded:
                ex0, ey0 = min(p[0] for p in excluded), min(p[1] for p in excluded)
                ex1, ey1 = max(p[0] for p in excluded), max(p[1] for p in excluded)
                if x1 > ex0 and x0 < ex1 and y1 > ey0 and y0 < ey1:
                    raise GeometryError('An object bounding rectangle overlaps the target bed exclusion area. Review placement in Orca.')
    if not placed:
        raise GeometryError('The project has no printable placed mesh objects.')
