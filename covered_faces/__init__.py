# SPDX-License-Identifier: GPL-3.0-or-later
"""Select > Select All by Trait > Covered Faces.

A face is covered when every point of it is closed off by other parts of the
piece, so neither the camera nor light can ever reach it:

* contact: another part's face lies on it (within the contact distance),
  facing the right way, and together those faces cover all of it;
* buried: the rest of it sits inside other closed parts.

Every object in Edit Mode counts as part of the piece, and every loose part
counts as its own part, so joined meshes work too. A part with holes counts
as closed when every hole would itself be a covered face (a neighbour seals
it), so it can run again after cleaning by hand; real openings stay open.
"""

import inspect

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import area_tri, delaunay_2d_cdt

# Faces count as parallel within about one degree.
_COS_PARALLEL = 0.9998
# Three skew directions for the inside test; the majority wins.
_RAY_DIRS = (
    Vector((0.5774, 0.5773, 0.5775)).normalized(),
    Vector((-0.7071, 0.1310, 0.6947)).normalized(),
    Vector((0.2113, -0.9301, 0.3003)).normalized(),
)
# Sample grid per triangle, used only where the region crosses a part's surface.
_SAMPLE_STEPS = 8


class _Face:
    __slots__ = ("mesh_key", "index", "comp", "closed", "co", "n", "c", "r",
                 "lo", "hi", "hide")


def _record(mesh_key, index, comp, co, n, hide):
    rec = _Face()
    rec.mesh_key = mesh_key
    rec.index = index
    rec.comp = comp
    rec.closed = False
    rec.co = co
    rec.n = n.normalized()
    rec.c = sum(co, Vector()) / len(co)
    rec.r = max((p - rec.c).length for p in co)
    rec.lo = Vector([min(p[k] for p in co) for k in range(3)])
    rec.hi = Vector([max(p[k] for p in co) for k in range(3)])
    rec.hide = hide
    return rec


def _gather(objects):
    """World-space faces of every object, plus a patch over every hole.

    Returns (faces, patches, closed, holed):
    faces    face records;
    patches  {part: [records]}, one patch per hole, wound like the face that
             would fill it, so its normal points out of the part;
    closed   parts with no holes (every edge has two faces, same winding);
    holed    parts whose only flaw is holes with clean borders.
    """
    faces, patches = [], {}
    closed, holed = set(), set()
    for ob in objects:
        bm = bmesh.from_edit_mesh(ob.data)
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        bm.faces.index_update()
        mat = ob.matrix_world
        nmat = mat.inverted_safe().transposed().to_3x3()

        # Loose parts: union-find over vertices joined by edges.
        parent = list(range(len(bm.verts)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for e in bm.edges:
            a, b = find(e.verts[0].index), find(e.verts[1].index)
            if a != b:
                parent[a] = b

        # Edges with one face are hole borders. Edges with more than two
        # faces, or two faces of opposite winding, make a part unusable as
        # a solid. Wire edges don't matter.
        bad, with_holes, border = set(), set(), {}
        for e in bm.edges:
            count = len(e.link_faces)
            if count == 0:
                continue
            root = find(e.verts[0].index)
            if count == 1:
                loop = e.link_loops[0]
                # The missing face ran along this edge the other way round.
                a, b = loop.vert.index, loop.link_loop_next.vert.index
                if b in border:
                    bad.add(root)  # two holes touch at a vertex
                border[b] = a
                with_holes.add(root)
            elif count > 2 or not e.is_contiguous:
                bad.add(root)

        done = set()
        for start in border:
            if start in done:
                continue
            ring, v = [], start
            while v is not None and v not in done:
                done.add(v)
                ring.append(v)
                v = border.get(v)
            root = find(start)
            if v != start:
                bad.add(root)
                continue
            co = [mat @ bm.verts[i].co for i in ring]
            area = Vector()
            for k in range(len(co)):
                area += co[k].cross(co[(k + 1) % len(co)])
            if area.length_squared == 0.0:
                continue  # a hole with no area lets nothing through
            comp = (ob.name, root)
            patches.setdefault(comp, []).append(_record(None, -1, comp, co, area, False))

        for f in bm.faces:
            n = nmat @ f.normal
            if n.length_squared == 0.0 or f.calc_area() == 0.0:
                continue
            root = find(f.verts[0].index)
            comp = (ob.name, root)
            if root in bad:
                pass
            elif root in with_holes:
                holed.add(comp)
            else:
                closed.add(comp)
            faces.append(_record(ob.data.name, f.index, comp,
                                 [mat @ v.co for v in f.verts], n, f.hide))
    return faces, patches, closed, holed


def _encloses_volume(recs, dist):
    """True when the faces, holes patched, wrap real volume: thicker than the
    contact distance on average. A plane patched with its own back does not."""
    volume = area = 0.0
    for rec in recs:
        p0 = rec.co[0]
        for k in range(1, len(rec.co) - 1):
            p1, p2 = rec.co[k], rec.co[k + 1]
            volume += p0.dot(p1.cross(p2)) / 6.0
            area += (p1 - p0).cross(p2 - p0).length / 2.0
    return volume > dist * area / 2.0 and volume > 0.0


def _bvh(recs):
    verts, polys = [], []
    for rec in recs:
        start = len(verts)
        verts.extend(rec.co)
        polys.append(range(start, start + len(rec.co)))
    return BVHTree.FromPolygons(verts, polys)


def _basis(n):
    u = n.orthogonal().normalized()
    return u, n.cross(u)


def _ccw(pts):
    area = 0.0
    for k in range(len(pts)):
        a, b = pts[k], pts[(k + 1) % len(pts)]
        area += a.x * b.y - b.x * a.y
    return area >= 0.0


def _contact_covers(F, faces, bvh_all, dist):
    """Faces of other parts that lie on F and hide it from the outside."""
    covers = []
    for _loc, _nor, gi, _d in bvh_all.find_nearest_range(F.c, F.r + dist):
        G = faces[gi]
        if G.comp == F.comp:
            continue
        d = F.n.dot(G.n)
        if abs(d) < _COS_PARALLEL:
            continue
        if G.closed:
            # A solid hides F only when the two face each other.
            if d > 0.0:
                continue
        else:
            # A surface (a plane, an open mesh) hides a solid's face when it
            # lies on it facing the same way: it is what the camera sees.
            # Facing into the solid, it is culled and the solid's face shows.
            if d < 0.0 or not F.closed:
                continue
        if not (all(abs(F.n.dot(p - F.c)) <= dist for p in G.co)
                or all(abs(G.n.dot(p - G.c)) <= dist for p in F.co)):
            continue
        covers.append(G)
    return covers


def _open_triangles(F, covers, dist):
    """The parts of F that the contact faces leave open, as 3D triangles."""
    u, v = _basis(F.n)
    o = F.c
    coords, polys = [], []
    for rec in [F] + covers:
        pts = [Vector(((p - o).dot(u), (p - o).dot(v))) for p in rec.co]
        idx = list(range(len(coords), len(coords) + len(pts)))
        if not _ccw(pts):
            idx.reverse()
        coords.extend(pts)
        polys.append(idx)

    eps = max(dist, 1e-6)
    out_v, _e, out_f, _ov, _oe, out_orig = delaunay_2d_cdt(coords, [], polys, 1, eps)
    tris = []
    for fv, orig in zip(out_f, out_orig):
        if orig != [0]:
            continue  # outside F, or inside F and covered
        a, b, c = (out_v[k] for k in fv)
        area = area_tri(a, b, c)
        longest = max((a - b).length, (b - c).length, (c - a).length)
        # Strips thinner than the contact distance count as closed.
        if longest == 0.0 or 2.0 * area / longest <= dist:
            continue
        tris.append([o + u * p.x + v * p.y for p in (a, b, c)])
    return tris


def _inside(tree, p):
    votes = 0
    for d in _RAY_DIRS:
        hits, origin = 0, p
        for _ in range(10000):
            loc, _nor, _idx, _dist = tree.ray_cast(origin, d)
            if loc is None:
                break
            hits += 1
            origin = loc + d * 1e-6
        votes += hits & 1
    return votes >= 2


def _samples(tri):
    a, b, c = tri
    cen = (a + b + c) / 3.0
    steps = _SAMPLE_STEPS
    pts = []
    for i in range(steps + 1):
        for j in range(steps + 1 - i):
            s, t = i / steps, j / steps
            p = a * s + b * t + c * (1.0 - s - t)
            pts.append(cen + (p - cen) * 0.98)
    return pts


def _buried(F, tris, solids, dist):
    """True when every open part of F sits inside other closed parts."""
    cand = [tree for comp, (tree, lo, hi) in solids.items()
            if comp != F.comp
            and all(lo[k] <= F.hi[k] + dist and hi[k] >= F.lo[k] - dist for k in range(3))]
    if not cand:
        return False

    shift = F.n * max(dist * 0.5, 1e-6)
    pushed = [[p + shift for p in t] for t in tris]
    verts = [p for t in pushed for p in t]
    region = BVHTree.FromPolygons(verts, [(3 * k, 3 * k + 1, 3 * k + 2) for k in range(len(pushed))])
    # If the pushed region crosses no part's surface, each triangle is wholly
    # inside or outside every part, and its centre decides. Otherwise sample it.
    crosses = any(region.overlap(tree) for tree in cand)
    for t in pushed:
        pts = _samples(t) if crosses else [(t[0] + t[1] + t[2]) / 3.0]
        for p in pts:
            if not any(_inside(tree, p) for tree in cand):
                return False
    return True


def _is_covered(F, recs, bvh_all, solids, dist, use_buried):
    covers = _contact_covers(F, recs, bvh_all, dist)
    if not covers and not use_buried:
        return False
    tris = _open_triangles(F, covers, dist)
    if not tris:
        return True
    return use_buried and _buried(F, tris, solids, dist)


def _world(faces, patches, closed, sealed):
    """Records, BVH and solids for a given set of sealed parts."""
    solid = closed | sealed
    recs = faces + [p for comp in sealed for p in patches.get(comp, ())]
    for rec in recs:
        rec.closed = rec.comp in solid
    by_comp = {}
    for rec in recs:
        if rec.closed:
            by_comp.setdefault(rec.comp, []).append(rec)
    solids = {}
    for comp, part in by_comp.items():
        lo = Vector([min(r.lo[k] for r in part) for k in range(3)])
        hi = Vector([max(r.hi[k] for r in part) for k in range(3)])
        solids[comp] = (_bvh(part), lo, hi)
    return recs, _bvh(recs), solids


def find_covered(objects, dist, use_buried):
    """{mesh name: set of face indices} covered in every instance of the mesh."""
    faces, patches, closed, holed = _gather(objects)
    if not faces:
        return {}
    by_comp = {}
    for rec in faces:
        by_comp.setdefault(rec.comp, []).append(rec)
    holed = {comp for comp in holed
             if _encloses_volume(by_comp[comp] + patches.get(comp, []), dist)}

    # A part with holes counts as closed when every hole would itself be a
    # covered face: a neighbour lies on it, or it sits inside one. That is
    # what cleaning leaves behind; a real opening (a bucket's top) is not.
    # Start by trusting every holed part and drop the ones whose patches
    # fail, until nothing changes. Starting trusting lets two cleaned parts
    # seal each other (two boxes that both lost their contact faces).
    sealed = set(holed)
    while True:
        recs, bvh_all, solids = _world(faces, patches, closed, sealed)
        failed = {comp for comp in sealed
                  if not all(_is_covered(p, recs, bvh_all, solids, dist, True)
                             for p in patches.get(comp, ()))}
        if not failed:
            break
        sealed -= failed

    covered, seen = {}, {}
    for F in faces:
        if F.hide:
            continue
        key = (F.mesh_key, F.index)
        seen[key] = seen.get(key, 0) + 1
        if _is_covered(F, recs, bvh_all, solids, dist, use_buried):
            covered[key] = covered.get(key, 0) + 1

    # A mesh shared by several objects: select a face only if it is covered
    # in every one of them.
    result = {}
    for key, count in covered.items():
        if count == seen[key]:
            result.setdefault(key[0], set()).add(key[1])
    return result


class MESH_OT_select_covered_faces(bpy.types.Operator):
    """Select faces that other parts cover completely, so they can never be seen"""

    bl_idname = "mesh.select_covered_faces"
    bl_label = "Select Covered Faces"
    bl_options = {'REGISTER', 'UNDO'}

    extend: BoolProperty(
        name="Extend",
        description="Extend the selection",
        default=False,
    )
    distance: FloatProperty(
        name="Contact Distance",
        description="Gaps up to this size count as touching",
        default=0.0001,
        min=0.0,
        soft_max=0.01,
        step=0.001,
        precision=5,
        subtype='DISTANCE',
    )
    use_buried: BoolProperty(
        name="Buried Faces",
        description="Also select faces sunk inside other closed parts",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        objects = [ob for ob in context.objects_in_mode if ob.type == 'MESH']
        # Blender puts only one user of a shared mesh into Edit Mode. Its other
        # users in the scene share every deletion, so they are checked too.
        meshes = {ob.data for ob in objects}
        instances = objects + [ob for ob in context.view_layer.objects
                               if ob.data in meshes and ob not in objects]
        result = find_covered(instances, self.distance, self.use_buried)

        ts = context.tool_settings
        if tuple(ts.mesh_select_mode) != (False, False, True):
            ts.mesh_select_mode = (False, False, True)

        total = 0
        for me in {ob.data for ob in objects}:
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()
            if not self.extend:
                for seq in (bm.verts, bm.edges, bm.faces):
                    for elem in seq:
                        elem.select = False
                bm.select_history.clear()
            for idx in result.get(me.name, ()):
                bm.faces[idx].select_set(True)
                total += 1
            bm.select_flush_mode()
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)

        self.report({'INFO'}, f"{total} covered face{'s' if total != 1 else ''} selected")
        return {'FINISHED'}


# Menu: put "Covered Faces" right under Blender's own "Interior Faces".

_KNOWN_TRAIT_MENU = '''
    def draw(self, context):
        layout = self.layout
        _is_vert_mode, _is_edge_mode, is_face_mode = context.tool_settings.mesh_select_mode
        if is_face_mode is False:
            layout.operator("mesh.select_non_manifold", text="Non Manifold")
        layout.operator("mesh.select_loose", text="Loose Geometry")
        layout.operator("mesh.select_interior_faces", text="Interior Faces")
        layout.operator("mesh.select_face_by_sides", text="Faces by Sides")
        layout.operator("mesh.select_by_pole_count", text="Poles by Count")
        layout.separator()
        layout.operator("mesh.select_ungrouped", text="Ungrouped Vertices")
'''


def _trait_menu_draw(self, context):
    layout = self.layout
    _is_vert_mode, _is_edge_mode, is_face_mode = context.tool_settings.mesh_select_mode
    if is_face_mode is False:
        layout.operator("mesh.select_non_manifold", text="Non Manifold")
    layout.operator("mesh.select_loose", text="Loose Geometry")
    layout.operator("mesh.select_interior_faces", text="Interior Faces")
    layout.operator(MESH_OT_select_covered_faces.bl_idname, text="Covered Faces")
    layout.operator("mesh.select_face_by_sides", text="Faces by Sides")
    layout.operator("mesh.select_by_pole_count", text="Poles by Count")
    layout.separator()
    layout.operator("mesh.select_ungrouped", text="Ungrouped Vertices")


def _trait_menu_append(self, context):
    self.layout.operator(MESH_OT_select_covered_faces.bl_idname, text="Covered Faces")


_original_draw = None


def _lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def register():
    global _original_draw
    bpy.utils.register_class(MESH_OT_select_covered_faces)
    menu = bpy.types.VIEW3D_MT_edit_mesh_select_by_trait
    try:
        source = inspect.getsource(menu.draw)
    except (OSError, TypeError):
        source = ""
    if _lines(source) == _lines(_KNOWN_TRAIT_MENU):
        _original_draw = menu.draw
        menu.draw = _trait_menu_draw
    else:
        # A Blender whose menu differs from the one we know: add at the end.
        menu.append(_trait_menu_append)


def unregister():
    global _original_draw
    menu = bpy.types.VIEW3D_MT_edit_mesh_select_by_trait
    if _original_draw is not None:
        menu.draw = _original_draw
        _original_draw = None
    else:
        menu.remove(_trait_menu_append)
    bpy.utils.unregister_class(MESH_OT_select_covered_faces)
