"""Renders the raw pictures for the README: the hero animation frames and the
four rule panels, plus label anchors (JSON) for compose.py.

Run:  blender -b --factory-startup --python docs/visuals/render_visuals.py
Then: python docs/visuals/compose.py
"""

import json
import math
import os
import sys

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import covered_faces  # noqa: E402

covered_faces.register()
OUT = os.path.join(ROOT, "docs", "visuals", "_render")
os.makedirs(os.path.join(OUT, "hero"), exist_ok=True)

GREY = (0.60, 0.60, 0.58, 1.0)
DARK = (0.36, 0.37, 0.39, 1.0)
WOOD = (0.55, 0.42, 0.30, 1.0)
PAPER = (0.78, 0.74, 0.64, 1.0)
RED = (0.55, 0.16, 0.14, 1.0)
BLUE = (0.30, 0.50, 0.85, 1.0)
ORANGE = (1.00, 0.48, 0.02, 1.0)


# --- scene helpers ---------------------------------------------------------

def reset():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.cameras):
        for item in list(coll):
            coll.remove(item)
    _mats.clear()
    bpy.context.view_layer.update()


def setup(width, height, culling=True):
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = 'Standard'
    sh = sc.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'MATERIAL'
    sh.show_cavity = True
    sh.cavity_type = 'BOTH'
    sh.show_object_outline = True
    sh.object_outline_color = (0.05, 0.05, 0.06)
    sh.show_specular_highlight = True
    sh.show_backface_culling = culling
    sc.display.render_aa = '16'
    if sc.world is None:
        sc.world = bpy.data.worlds.new("World")
    sc.world.color = (0.030, 0.032, 0.036)


_mats = {}
_base = {}


def mat(name, color):
    m = _mats.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        _mats[name] = m
    m.diffuse_color = color
    return m


def _link(name, bm, loc, color):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    me.materials.append(mat("base_" + name, color))
    me.materials.append(mat("orange_" + name, ORANGE))
    _base[name] = color
    return ob


def box(name, size, loc, color=GREY):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    return _link(name, bm, loc, color)


def cyl(name, radius, depth, loc, color=GREY, segments=24):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius,
                          radius2=radius, depth=depth)
    return _link(name, bm, loc, color)


def plane(name, size, loc, up=True, color=BLUE):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2)
    if not up:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    return _link(name, bm, loc, color)


def arrow(name, base, direction, length=0.45, color=BLUE):
    """A small normal arrow; not part of the piece."""
    d = Vector(direction).normalized()
    bm = bmesh.new()
    shaft = length * 0.68
    bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=0.018, radius2=0.018,
                          depth=shaft, matrix=_along(d, shaft / 2))
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.055, radius2=0.0,
                          depth=length - shaft, matrix=_along(d, shaft + (length - shaft) / 2))
    return _link(name, bm, base, color)


def _along(d, dist):
    from mathutils import Matrix
    rot = Vector((0, 0, 1)).rotation_difference(d).to_matrix().to_4x4()
    return Matrix.Translation(d * dist) @ rot


def cut(ob, *dirs):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    kill = [f for f in bm.faces for d in dirs
            if f.normal["xyz".index(d[1])] * (1 if d[0] == "+" else -1) > 0.99]
    bmesh.ops.delete(bm, geom=kill, context='FACES_ONLY')
    bm.to_mesh(ob.data)
    bm.free()


def select_covered(objs):
    bpy.context.view_layer.update()
    for ob in bpy.data.objects:
        ob.select_set(ob in objs)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.select_covered_faces()
    bpy.ops.object.mode_set(mode='OBJECT')
    count = 0
    for ob in objs:
        for p in ob.data.polygons:
            p.material_index = 1 if p.select else 0
            count += p.select
    return count


def camera(loc, target, lens=50):
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam.data.lens = lens
    aim(cam, loc, target)
    return cam


def aim(cam, loc, target):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()


def face_point(ob, normal, pick=None):
    """World centre of ob's face whose normal points along `normal`."""
    bpy.context.view_layer.update()
    n = Vector(normal).normalized()
    rot = ob.matrix_world.to_3x3()
    faces = [p for p in ob.data.polygons if (rot @ p.normal).normalized().dot(n) > 0.95]
    if pick:
        faces.sort(key=pick)
    return ob.matrix_world @ faces[0].center


def project(co):
    sc = bpy.context.scene
    v = world_to_camera_view(sc, sc.camera, Vector(co))
    return [round(v.x * sc.render.resolution_x), round((1 - v.y) * sc.render.resolution_y)]


def render(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def faces_total(objs):
    return sum(len(ob.data.polygons) for ob in objs)


# --- hero animation: crates on a platform ----------------------------------

def hero():
    reset()
    setup(960, 600, culling=False)
    parts = {}
    parts["Platform"] = box("Platform", (2.6, 1.7, 0.2), (0, 0, 0.1), DARK)
    parts["CrateA"] = box("CrateA", (0.8, 0.8, 0.8), (-0.55, 0.05, 0.6), WOOD)
    parts["CrateB"] = box("CrateB", (0.5, 0.5, 0.5), (-0.5, 0.1, 1.25), WOOD)
    parts["CrateB"].rotation_euler.z = math.radians(18)
    parts["CrateC"] = box("CrateC", (0.6, 0.6, 0.6), (0.15, 0.0, 0.5), WOOD)
    parts["Barrel"] = cyl("Barrel", 0.27, 0.72, (0.85, 0.3, 0.56), RED)
    parts["Post"] = cyl("Post", 0.04, 1.55, (0.95, -0.55, 0.825), PAPER, segments=12)

    objs = list(parts.values())
    before = faces_total(objs)
    selected = select_covered(objs)
    after = before - selected

    offsets = {
        "Platform": (0, 0, -0.70),
        "CrateA": (-0.15, 0, 0.35),
        "CrateB": (0.05, 0, 0.80),
        "CrateC": (0.50, -0.1, 0.40),
        "Barrel": (0.50, 0.1, 0.50),
        "Post": (0.45, -0.25, 0.55),
    }
    base = {name: ob.location.copy() for name, ob in parts.items()}

    target = Vector((0.1, 0, 0.85))
    cam = camera((0, 0, 0), target, lens=38)

    def ease(t):
        t = max(0.0, min(1.0, t))
        return t * t * (3 - 2 * t)

    def cam_at(f):
        ang = math.radians(-128 + 34 * f / frames)
        return target + Vector((math.cos(ang) * 5.6, math.sin(ang) * 5.6, 1.35))

    frames = 172
    # Each part turns as it comes apart, so its covered face points at the
    # camera (bottoms would stay dark from below).
    from mathutils import Quaternion
    bpy.context.view_layer.update()
    base_rot = {name: ob.rotation_euler.to_quaternion() for name, ob in parts.items()}
    turn = {}
    for name, ob in parts.items():
        rot = ob.matrix_world.to_3x3()
        normals = [(rot @ p.normal).normalized() for p in ob.data.polygons if p.material_index == 1]
        turn[name] = Quaternion()
        if not normals:
            continue
        n = min(normals, key=lambda v: v.z)  # the lowest-facing one: usually the bottom
        centre = base[name] + Vector(offsets[name])
        d = (cam_at(70) - centre).normalized()
        if n.dot(d) < 0.5:
            full = n.rotation_difference(d)
            turn[name] = Quaternion().slerp(full, 0.8)

    # Frames: piece 0-15, apart and turn 16-39, glow 40-51, hold, delete at
    # 96, together 106-129, result.
    timeline = []
    deleted = False
    for f in range(frames):
        e = ease((f - 16) / 24) if f < 106 else 1 - ease((f - 106) / 24)
        for name, ob in parts.items():
            ob.location = base[name] + Vector(offsets[name]) * e
            ob.rotation_euler = (Quaternion().slerp(turn[name], e) @ base_rot[name]).to_euler()
        g = ease((f - 40) / 12)
        for name in parts:
            c = _base[name]
            _mats["orange_" + name].diffuse_color = [c[k] * (1 - g) + ORANGE[k] * g for k in range(3)] + [1.0]
        if f >= 96 and not deleted:
            for ob in objs:
                bm = bmesh.new()
                bm.from_mesh(ob.data)
                kill = [fc for fc in bm.faces if fc.material_index == 1]
                bmesh.ops.delete(bm, geom=kill, context='FACES_ONLY')
                bm.to_mesh(ob.data)
                bm.free()
            deleted = True
        aim(cam, cam_at(f), target)
        if f < 16:
            key = "piece"
        elif f < 40:
            key = "apart"
        elif f < 66:
            key = "selected"
        elif f < 96:
            key = "below"
        elif f < 106:
            key = "deleted"
        elif f < 134:
            key = "together"
        else:
            key = "result"
        timeline.append(key)
        bpy.context.scene.frame_set(0)
        render(os.path.join(OUT, "hero", f"{f:03d}.png"))
    return {"before": before, "after": after, "selected": selected, "parts": len(objs),
            "timeline": timeline}


# --- panels ------------------------------------------------------------------

FOOT = (0.30, 0.31, 0.33, 1.0)


def tilt(ob, axis, degrees):
    from mathutils import Matrix
    rot = Matrix.Rotation(math.radians(degrees), 3, axis) @ ob.rotation_euler.to_matrix()
    ob.rotation_euler = rot.to_euler()
    bpy.context.view_layer.update()


def sel_point(ob):
    """World centre of the object's first selected (orange) face."""
    bpy.context.view_layer.update()
    for p in ob.data.polygons:
        if p.material_index == 1:
            return ob.matrix_world @ p.center
    raise ValueError(ob.name + " has no selected face")


def local_point(ob, co):
    bpy.context.view_layer.update()
    return ob.matrix_world @ Vector(co)


def footprint(name, sx, sy, loc, rot=(0, 0, 0)):
    """A dark patch marking where a moved part sat."""
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    bmesh.ops.scale(bm, vec=(sx, sy, 1), verts=bm.verts)
    ob = _link(name, bm, loc, FOOT)
    ob.rotation_euler = rot
    return ob


def panel_contact():
    reset()
    setup(1400, 760)
    thick = box("Thick", (2, 1.4, 0.8), (0, 0, 0.4), GREY)
    slim = box("Slim", (0.9, 0.9, 0.9), (0, 0, 1.25), GREY)
    select_covered([thick, slim])
    slim.location = (-0.2, -0.2, 2.2)
    tilt(slim, 'X', -58)
    footprint("Foot", 0.9, 0.9, (0, 0, 0.803))
    camera((3.4, -6.2, 4.0), (0, 0, 1.15), lens=40)
    return [
        {"at": project(sel_point(slim)), "text": "Bottom of the small box: fully covered, selected", "dx": 240, "dy": -170, "hot": True},
        {"at": project(Vector((-0.2, 0.0, 0.8))), "text": "Where it sat", "dx": -420, "dy": -10, "hot": False},
        {"at": project(local_point(thick, (0.75, -0.45, 0.4))), "text": "Top of the big box: only partly covered, kept", "dx": 90, "dy": 120, "hot": False},
    ]


def panel_planes():
    reset()
    setup(1400, 760)
    # Left: a plane lying on a box, facing out.
    b1 = box("BoxA", (1, 1, 1), (-1.6, 0, 0.5), GREY)
    p1 = plane("PlaneA", 1.4, (-1.6, 0, 1.0), up=True)
    # Right: a plane under a box, facing into it.
    b2 = box("BoxB", (1, 1, 1), (1.6, 0, 0.9), GREY)
    p2 = plane("PlaneB", 0.9, (1.6, 0, 0.4), up=True)
    select_covered([b1, p1, b2, p2])
    p1.location.z += 0.8
    b2.location.z += 0.8
    arrow("ArrowA", (-1.6, 0, 1.8), (0, 0, 1))
    arrow("ArrowB", (1.6, 0, 0.4), (0, 0, 1))
    camera((0.35, -6.8, 3.6), (0.35, 0, 1.0), lens=34)
    return [
        {"at": project(sel_point(b1)), "text": "Box top under a plane facing out: selected", "dx": -300, "dy": 190, "hot": True},
        {"at": project(Vector((-2.25, -0.6, 1.8))), "text": "The plane is what you see: kept", "dx": -40, "dy": -170, "hot": False},
        {"at": project(sel_point(p2) + Vector((0.25, -0.2, 0))), "text": "Plane facing into the box: selected", "dx": 10, "dy": 150, "hot": True},
        {"at": project(local_point(b2, (0.5, -0.5, -0.45))), "text": "So the box bottom shows: kept", "dx": 40, "dy": -30, "hot": False},
    ]


def panel_buried():
    reset()
    setup(1400, 760)
    wall = box("Wall", (0.6, 2.4, 2.0), (0, 0, 1.0), DARK)
    beam = box("Beam", (2.2, 0.4, 0.4), (1.0, 0, 1.1), GREY)   # x from -0.1 to 2.1
    select_covered([wall, beam])
    beam.location = (2.1, -0.7, 1.1)
    tilt(beam, 'Z', 62)
    footprint("Foot", 0.4, 0.4, (0.303, 0, 1.1), rot=(0, math.radians(90), 0))
    camera((2.6, -6.4, 3.0), (1.1, 0, 1.0), lens=40)
    return [
        {"at": project(sel_point(beam)), "text": "End cap, sunk 0.2 m into the wall: selected", "dx": -560, "dy": 170, "hot": True},
        {"at": project(local_point(beam, (0.5, -0.2, 0.0))), "text": "Sides, partly outside: kept", "dx": 120, "dy": 150, "hot": False},
        {"at": project(Vector((0.3, -0.2, 1.1))), "text": "Where it went in", "dx": -330, "dy": -140, "hot": False},
    ]


def panel_holes():
    reset()
    setup(1400, 760, culling=False)
    # Left: an open bucket with a block inside.
    bucket = box("Bucket", (1.1, 1.1, 0.75), (-1.7, 0, 0.375), GREY)
    cut(bucket, "+z")
    block = box("Block", (0.45, 0.45, 0.45), (-1.7, 0, 0.3), PAPER)
    # Right: two boxes already cleaned where they touch, a block across the seam.
    low = box("Low", (1.1, 1.1, 0.8), (1.5, 0, 0.4), GREY)
    high = box("High", (1.1, 1.1, 0.8), (1.5, 0, 1.2), GREY)
    cut(low, "+z")
    cut(high, "-z")
    core = box("Core", (0.45, 0.45, 0.5), (1.5, 0, 0.8), PAPER)
    select_covered([bucket, block, low, high, core])
    high.location = (1.5, 0.2, 2.35)
    tilt(high, 'X', -50)
    camera((0.0, -7.0, 4.6), (0, 0, 1.05), lens=36)
    return [
        {"at": project(local_point(block, (0, 0, 0.225))), "text": "Open top, you can see in: block kept", "dx": -150, "dy": -230, "hot": False},
        {"at": project(sel_point(core)), "text": "Two cleaned boxes seal each other: block selected", "dx": -40, "dy": 210, "hot": True},
        {"at": project(local_point(high, (0.3, 0, -0.4))), "text": "Contact faces already deleted", "dx": 150, "dy": -60, "hot": False},
    ]


if __name__ == "__main__":
    labels_path = os.path.join(OUT, "labels.json")
    if os.environ.get("ONLY_PANELS") and os.path.exists(labels_path):
        with open(labels_path, encoding="utf-8") as fh:
            data = {"hero": json.load(fh)["hero"]}
    else:
        data = {"hero": hero()}
    for name, fn in (("contact", panel_contact), ("planes", panel_planes),
                     ("buried", panel_buried), ("holes", panel_holes)):
        labels = fn()
        render(os.path.join(OUT, f"panel_{name}.png"))
        data[name] = labels
    with open(os.path.join(OUT, "labels.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    print("VISUALS", json.dumps({k: v for k, v in data["hero"].items() if k != "timeline"}))
