"""Background tests for Select Covered Faces.

Run:  blender -b --factory-startup --python tests/run_tests.py
Each case builds objects, runs the operator in Edit Mode and compares the
selected faces (by object and face direction) with what a modeller would pick.
"""

import os
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import covered_faces  # noqa: E402

covered_faces.register()


def clear():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for me in list(bpy.data.meshes):
        bpy.data.meshes.remove(me)
    bpy.context.view_layer.update()


def box(name, size, loc, rot=None, flip=False):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if flip:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(me)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    if rot:
        ob.rotation_euler = rot
    return ob


def plane(name, size, loc, normal_up=True, subdiv=0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=subdiv + 1, y_segments=subdiv + 1, size=size / 2)
    if not normal_up:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(me)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    return ob


def join(objs):
    for ob in bpy.data.objects:
        ob.select_set(False)
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    return objs[0]


def run(objs, **props):
    for ob in bpy.data.objects:
        ob.select_set(False)
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    t = time.perf_counter()
    bpy.ops.mesh.select_covered_faces(**props)
    dt = time.perf_counter() - t
    bpy.ops.object.mode_set(mode='OBJECT')
    picked = set()
    for ob in objs:
        rot = ob.matrix_world.to_3x3()
        for p in ob.data.polygons:
            if p.select:
                n = (rot @ p.normal).normalized()
                axis = max(range(3), key=lambda k: abs(n[k]))
                d = ("+" if n[axis] > 0 else "-") + "xyz"[axis]
                picked.add((ob.name, d, round((ob.matrix_world @ p.center)[axis], 3)))
    return picked, dt


results = []


def case(name, got, expected):
    ok = got == expected
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        print("   expected", sorted(expected) if isinstance(expected, set) else expected)
        print("   got     ", sorted(got) if isinstance(got, set) else got)


# 1. Slim box on a thick box: only the slim box's bottom.
clear()
a = box("Thick", (2, 2, 1), (0, 0, 0.5))
b = box("Slim", (1, 1, 1), (0, 0, 1.5))
got, _ = run([a, b])
case("slim on thick: only the slim box's contact face", got, {("Slim", "-z", 1.0)})

# 2. Equal boxes face to face: both contact faces.
clear()
a = box("A", (1, 1, 1), (0, 0, 0.5))
b = box("B", (1, 1, 1), (0, 0, 1.5))
got, _ = run([a, b])
case("equal boxes: both contact faces", got, {("A", "+z", 1.0), ("B", "-z", 1.0)})

# 3. One face covered by two boxes side by side.
clear()
a = box("Base", (2, 1, 1), (0, 0, 0.5))
b = box("Left", (1, 1, 1), (-0.5, 0, 1.5))
c = box("Right", (1, 1, 1), (0.5, 0, 1.5))
got, _ = run([a, b, c])
case("covered by two boxes: base top selected",
     got, {("Base", "+z", 1.0), ("Left", "-z", 1.0), ("Right", "-z", 1.0),
           ("Left", "+x", 0.0), ("Right", "-x", 0.0)})

# 4. Two boxes with a gap between them: base top stays.
clear()
a = box("Base", (2, 1, 1), (0, 0, 0.5))
b = box("Left", (0.9, 1, 1), (-0.55, 0, 1.5))
c = box("Right", (0.9, 1, 1), (0.55, 0, 1.5))
got, _ = run([a, b, c])
case("gap between covers: base top kept",
     got, {("Left", "-z", 1.0), ("Right", "-z", 1.0)})

# 5. Plane lying on a box, facing out: box top selected, plane kept.
clear()
a = box("Box", (1, 1, 1), (0, 0, 0.5))
p = plane("Plane", 2, (0, 0, 1.0), normal_up=True)
got, _ = run([a, p])
case("plane facing out: box top selected", got, {("Box", "+z", 1.0)})

# 6. Plane under a box, facing into it: plane selected, box bottom kept.
clear()
a = box("Box", (1, 1, 1), (0, 0, 0.5))
p = plane("Plane", 1, (0, 0, 0.0), normal_up=True)
got, _ = run([a, p])
case("plane facing into the box: plane selected", got, {("Plane", "+z", 0.0)})

# 7. Box covered by a subdivided plane (many small cover faces).
clear()
a = box("Box", (1, 1, 1), (0, 0, 0.5))
p = plane("Plane", 1.5, (0, 0, 1.0), normal_up=True, subdiv=4)
got, _ = run([a, p])
case("plane of many faces: box top selected", got, {("Box", "+z", 1.0)})

# 8. Same as 1 but joined into one object (loose parts).
clear()
a = box("Thick", (2, 2, 1), (0, 0, 0.5))
b = box("Slim", (1, 1, 1), (0, 0, 1.5))
j = join([a, b])
got, _ = run([j])
case("joined object: slim contact face", got, {(j.name, "-z", 1.0)})

# 9. Rotated and scaled pair.
clear()
a = box("Thick", (2, 2, 1), (0, 0, 0.5))
b = box("Slim", (1, 1, 1), (0, 0, 1.5))
bpy.context.view_layer.update()
for ob in (a, b):
    ob.matrix_world = Matrix.Rotation(0.6, 4, 'X') @ Matrix.Rotation(0.3, 4, 'Z') @ ob.matrix_world
bpy.context.view_layer.update()
got, _ = run([a, b])
case("rotated pair: one face on the slim box", {g[0] for g in got} == {"Slim"} and len(got) == 1, True)

# 10. Box end buried in a wall: end cap selected, sides kept.
clear()
w = box("Wall", (1, 4, 4), (0, 0, 0))
b = box("Beam", (2, 0.5, 0.5), (1.2, 0, 0))   # x from 0.2 to 2.2: end cap 0.2 inside wall
got, _ = run([w, b])
case("beam end buried in wall: end cap selected", got, {("Beam", "-x", 0.2)})
got, _ = run([w, b], use_buried=False)
case("buried off: nothing", got, set())

# 11. Small box fully inside a big one: all six faces.
clear()
w = box("Big", (4, 4, 4), (0, 0, 0))
b = box("Small", (1, 1, 1), (0.3, 0.2, 0.1))
got, _ = run([w, b])
case("box inside box: all six faces", {g for g in got if g[0] == "Small"} == got and len(got) == 6, True)

# 12. Buried in the union of two overlapping walls.
clear()
w1 = box("W1", (2, 4, 4), (0, 0, 0))
w2 = box("W2", (2, 4, 4), (1.5, 0, 0))
b = box("Small", (2, 0.5, 0.5), (0.8, 0, 0))   # x 0.0..1.8 spans both walls
got, _ = run([w1, w2, b])
small = {g for g in got if g[0] == "Small"}
case("buried across two walls: six small faces + the walls' inner faces",
     len(small) == 6 and got - small == {("W1", "+x", 1.0), ("W2", "-x", 0.5)}, True)

# 13. Same-direction coincident solid faces (z-fighting, not contact): none.
clear()
a = box("A", (1, 1, 1), (0, 0, 0.5))
b = box("B", (1, 1, 2), (0, 0, 0.0))  # B top at z=1 too, same direction as A top
got, _ = run([a, b])
case("coincident same-facing faces: neither top", not any(g[1] == "+z" for g in got), True)

# 14. A small gap below the contact distance counts as touching; above it does not.
clear()
a = box("Thick", (2, 2, 1), (0, 0, 0.5))
b = box("Slim", (1, 1, 1), (0, 0, 1.50005))
got, _ = run([a, b])
case("gap 0.05 mm, distance 0.1 mm: selected", got, {("Slim", "-z", 1.0)})
got, _ = run([a, b], distance=0.00001, use_pockets=False)
case("gap 0.05 mm, distance 0.01 mm, pockets off: kept", got, set())

# 15. Extend keeps the old selection; without it the old selection goes.
clear()
a = box("Thick", (2, 2, 1), (0, 0, 0.5))
b = box("Slim", (1, 1, 1), (0, 0, 1.5))
got, _ = run([a, b], extend=True)
case("extend: everything stays selected", len(got) == 12, True)

# 16. Linked duplicates: a face covered in one instance but not the other stays.
clear()
a = box("Thick", (2, 2, 1), (0, 0, 0.5))
b = box("Slim", (1, 1, 1), (0, 0, 1.5))
c = bpy.data.objects.new("Slim.lonely", b.data)
bpy.context.collection.objects.link(c)
c.location = (10, 0, 1.5)
got, _ = run([a, b, c])
case("linked duplicate in the open: nothing selected", got, set())

# 17. Speed: a stack of 400 boxes.
clear()
objs = []
for i in range(20):
    for k in range(20):
        objs.append(box(f"B{i}_{k}", (1, 1, 1), (i * 1.0, 0, k * 1.0)))
got, dt = run(objs)
print(f"     400 boxes, 2400 faces: {len(got)} selected in {dt:.2f} s")
case("stack of 400 boxes: every inner face (1520)", len(got), 1520)

# 17b. A board whose covered faces use all its corners (top and both ends):
#      only those three, not every face of it (vertex-mode flush bug, 1.1.0).
clear()
top = box("Top", (1.2, 0.8, 0.06), (0, 0, 0.75))
legs = [box(f"Leg{i}", (0.06, 0.06, 0.72), (sx * 0.54, -0.34, 0.36)) for i, sx in enumerate((1, -1))]
apron = box("Apron", (1.02, 0.03, 0.1), (0, -0.34, 0.67))
bpy.context.scene.tool_settings.mesh_select_mode = (True, False, False)
got, _ = run([top, apron] + legs)
case("board between legs under a top: only its top and two ends",
     {g for g in got if g[0] == "Apron"}, {("Apron", "+z", 0.72), ("Apron", "+x", 0.51), ("Apron", "-x", -0.51)})

# --- Parts already cleaned by hand (holes) -------------------------------

def cut(ob, *dirs):
    """Delete the faces whose normal points along any of dirs ('+z', '-x'...)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    kill = []
    for f in bm.faces:
        for d in dirs:
            axis = "xyz".index(d[1])
            if f.normal[axis] * (1 if d[0] == "+" else -1) > 0.99:
                kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context='FACES_ONLY')
    bm.to_mesh(ob.data)
    bm.free()


def only(got, name):
    return {g for g in got if g[0] == name}


# 18. Slim box already cleaned (bottom gone); a core sunk inside it.
clear()
a = box("Thick", (2, 2, 1), (0, 0, 0.5))
b = box("Slim", (1, 1, 1), (0, 0, 1.5))
cut(b, "-z")
core = box("Core", (0.4, 0.4, 0.4), (0, 0, 1.5))
got, _ = run([a, b, core])
case("cleaned slim box still holds a buried core", got == only(got, "Core") and len(got) == 6, True)

# 19. An open bucket: the core inside can be seen, nothing selected.
clear()
a = box("Bucket", (1, 1, 1), (0, 0, 0.5))
cut(a, "+z")
core = box("Core", (0.4, 0.4, 0.4), (0, 0, 0.4))
got, _ = run([a, core])
case("open bucket: core inside is kept", got, set())

# 20. Two boxes that both lost their contact faces seal each other.
clear()
a = box("A", (1, 1, 1), (0, 0, 0.5))
b = box("B", (1, 1, 1), (0, 0, 1.5))
cut(a, "+z")
cut(b, "-z")
core = box("Core", (0.4, 0.4, 0.4), (0, 0, 1.0))
got, _ = run([a, b, core])
case("two cleaned boxes seal each other: core selected", got == only(got, "Core") and len(got) == 6, True)

# 21. A chain of three cleaned boxes, core in the middle one.
clear()
a = box("A", (1, 1, 1), (0, 0, 0.5))
b = box("B", (1, 1, 1), (0, 0, 1.5))
c = box("C", (1, 1, 1), (0, 0, 2.5))
cut(a, "+z")
cut(b, "-z", "+z")
cut(c, "-z")
core = box("Core", (0.4, 0.4, 0.4), (0, 0, 1.5))
got, _ = run([a, b, c, core])
case("chain of cleaned boxes: core selected", got == only(got, "Core") and len(got) == 6, True)

# 22. Running again after cleaning one side: the other contact face goes too.
clear()
a = box("A", (1, 1, 1), (0, 0, 0.5))
b = box("B", (1, 1, 1), (0, 0, 1.5))
cut(a, "+z")
got, _ = run([a, b])
case("rerun after cleaning A: B's bottom selected", got, {("B", "-z", 1.0)})

# 23. Beam whose buried end cap was deleted: still a solid inside the wall.
clear()
w = box("Wall", (1, 4, 4), (0, 0, 0))
b = box("Beam", (2, 0.5, 0.5), (1.2, 0, 0))
cut(b, "-x")
core = box("Core", (0.2, 0.2, 0.2), (1.2, 0, 0))
got, _ = run([w, b, core])
case("cleaned beam still holds a buried core", got == only(got, "Core") and len(got) == 6, True)

# 24. Two open buckets rim to rim make a closed space.
clear()
a = box("Low", (1, 1, 1), (0, 0, 0.5))
b = box("High", (1, 1, 1), (0, 0, 1.5))
cut(a, "+z")
cut(b, "-z")
core = box("Core", (0.4, 0.4, 0.4), (0, 0, 1.0))
got, _ = run([a, b, core])
case("buckets rim to rim: core selected", got == only(got, "Core") and len(got) == 6, True)

# 25. A hole only partly covered stays open: core kept.
clear()
a = box("Bucket", (1, 1, 1), (0, 0, 0.5))
cut(a, "+z")
b = box("Lid", (0.6, 0.6, 0.2), (0, 0, 1.1))
core = box("Core", (0.3, 0.3, 0.3), (0, 0, 0.4))
got, _ = run([a, b, core])
case("lid smaller than the hole: core kept", only(got, "Core"), set())

# 26. A plane is not a paper-thin solid: box under a plane facing out, again.
clear()
a = box("Box", (1, 1, 1), (0, 0, 0.5))
p = plane("Plane", 2, (0, 0, 1.0), normal_up=True)
core = box("Core", (0.2, 0.2, 0.2), (0, 0, 1.0))  # half above the plane, in the open
got, _ = run([a, p, core])
case("plane stays a plane: box top selected, core's upper half not buried",
     ("Box", "+z", 1.0) in got and ("Core", "+z", 1.1) not in got, True)

# 27. A mirrored part (negative scale) with a hole still seals (1.1.1 read its
#     hole and volume inside out). Pockets off, so only the sealing counts.
clear()
a = box("Thick", (2, 2, 1), (0, 0, 0.5))
b = box("Slim", (1, 1, 1), (0, 0, 1.5))
cut(b, "-z")
b.scale = (-1, 1, 1)
core = box("Core", (0.4, 0.4, 0.4), (0, 0, 1.5))
got, _ = run([a, b, core], use_pockets=False)
case("mirrored cleaned box still holds a buried core", got == only(got, "Core") and len(got) == 6, True)

# --- Sealed pockets --------------------------------------------------------


def quad(name, pts):
    """One face through pts, its normal by the right-hand rule."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([Vector(p) for p in pts], [], [range(len(pts))])
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


def wall(posts=2):
    """A wall of two loose planes 3 cm apart (y 0 and 0.03, facing out), its
    gap shut by bars above and below and posts at the sides."""
    out = [
        quad("Front", [(-0.5, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (-0.5, 0, 0.5)]),
        quad("Back", [(-0.5, 0.03, 0.5), (0.5, 0.03, 0.5), (0.5, 0.03, -0.5), (-0.5, 0.03, -0.5)]),
        box("Top", (1.2, 0.03, 0.1), (0, 0.015, 0.55)),
        box("Bottom", (1.2, 0.03, 0.1), (0, 0.015, -0.55)),
    ]
    for i, x in enumerate((0.55, -0.55)[:posts]):
        out.append(box(f"Post{i}", (0.1, 0.03, 1.0), (x, 0.015, 0)))
    return out


# 28. A plate on the outside of such a wall (BED-03): its back sits on the
#     front plane, back to back, and looks into the shut gap: selected.
clear()
plate = box("Plate", (0.2, 0.05, 0.4), (0, -0.025, 0))
parts = [plate] + wall()
got, _ = run(parts)
case("plate on a wall of two planes: its back selected", only(got, "Plate"), {("Plate", "+y", 0.0)})
case("the wall's own planes are kept", only(got, "Front") | only(got, "Back"), set())
got, _ = run(parts, use_pockets=False)
case("pockets off: plate back kept", only(got, "Plate"), set())
got, _ = run(parts, pocket_depth=0.02)
case("gap deeper than the pocket depth: plate back kept", only(got, "Plate"), set())

# 29. The same wall with one side open: the gap can be seen into, plate kept.
clear()
plate = box("Plate", (0.2, 0.05, 0.4), (0, -0.025, 0))
got, _ = run([plate] + wall(posts=1))
case("wall gap open at one side: plate back kept", only(got, "Plate"), set())

# 30. A closed crate of six planks: its inside is a closed space, but too
#     deep for a pocket (someone could look in there), so the floor is kept.
clear()
planks = [box("Floor", (1, 1, 0.05), (0, 0, -0.475)), box("Lid", (1, 1, 0.05), (0, 0, 0.475)),
          box("W0", (0.05, 1, 0.9), (0.475, 0, 0)), box("W1", (0.05, 1, 0.9), (-0.475, 0, 0)),
          box("W2", (0.9, 0.05, 0.9), (0, 0.475, 0)), box("W3", (0.9, 0.05, 0.9), (0, -0.475, 0))]
got, _ = run(planks)
case("closed crate: the floor's inside face is kept", ("Floor", "+z", -0.45) in got, False)

print(f"\n{sum(results)}/{len(results)} passed")
