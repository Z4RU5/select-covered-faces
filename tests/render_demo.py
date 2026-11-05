"""Renders docs/demo_exploded.png: three setups pulled apart, selected faces in red.

Run:  blender -b --factory-startup --python tests/render_demo.py
"""
import os, sys, bpy, bmesh, math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from mathutils import Vector
sys.path.insert(0, ROOT)
import covered_faces
covered_faces.register()
for ob in list(bpy.data.objects): bpy.data.objects.remove(ob)
def box(name, size, loc):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bm.to_mesh(me); ob = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(ob); ob.location = loc; return ob
def plane(name, size, loc):
    me = bpy.data.meshes.new(name); bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size/2); bm.to_mesh(me)
    ob = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(ob); ob.location = loc; return ob
objs = [
  box("Thick", (2, 2, 1), (0, 0, 0.5)), box("Slim", (1, 1, 1), (0, 0, 1.5)),            # slim on thick
  box("BoxP", (1, 1, 1), (3.5, 0, 0.5)), plane("PlaneP", 1.6, (3.5, 0, 1.0)),           # plane on box
  box("Wall", (1, 3, 3), (7, 0, 1.5)), box("Beam", (2, 0.5, 0.5), (8.2, 0, 1.5)),        # beam buried
]
bpy.context.view_layer.update()
for o in bpy.data.objects: o.select_set(o in objs)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.select_covered_faces()
bpy.ops.object.mode_set(mode='OBJECT')
grey = bpy.data.materials.new("grey"); grey.diffuse_color = (0.75, 0.75, 0.75, 1)
red = bpy.data.materials.new("red"); red.diffuse_color = (0.9, 0.08, 0.05, 1)
blue = bpy.data.materials.new("plane"); blue.diffuse_color = (0.35, 0.55, 0.85, 1)
explode = {"Slim": (0, 0, 1.2), "PlaneP": (0, 0, 0.9), "Beam": (1.3, 0, 0)}
for o in objs:
    o.data.materials.append(blue if o.name == "PlaneP" else grey); o.data.materials.append(red)
    for p in o.data.polygons: p.material_index = 1 if p.select else 0
    o.location += Vector(explode.get(o.name, (0, 0, 0)))
    if o.name == "Slim": o.rotation_euler = (math.radians(-65), 0, 0)
    if o.name == "Beam": o.rotation_euler = (0, 0, math.radians(55))
sc = bpy.context.scene
sc.render.engine = 'BLENDER_WORKBENCH'
sh = sc.display.shading; sh.color_type = 'MATERIAL'; sh.light = 'STUDIO'; sh.show_cavity = False
sh.show_backface_culling = True
sc.render.resolution_x, sc.render.resolution_y = 1600, 800
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.location = (3.8, -13.0, 6.5); 
d = Vector((4.0, 0, 1.6)) - cam.location; cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
cam.data.lens = 34
sc.world = bpy.data.worlds.new("w"); sc.world.color = (0.12, 0.12, 0.13)
sc.render.filepath = os.path.join(ROOT, "docs", "demo_exploded.png")
bpy.ops.render.render(write_still=True)
print("COUNTS", {o.name: sum(p.select for p in o.data.polygons) for o in objs})
