"""Export a triangulated surface mesh (by named physical group) to JSON, for
rendering as an actual solid-looking 3D surface (as opposed to a bare point
cloud) in the interactive HTML viewer under macros/output/field_viewer.html.
"""

import json

import gmsh
import numpy as np


def export_surface_groups_json(
    surface_group_ids: dict[str, int], output_path: str
) -> None:
    """Write {"vertices": [[x,y,z], ...], "groups": {name: [[i,j,k], ...]}}.

    Each group's faces are lists of indices into the shared "vertices" array.
    Call this right after gmsh.model.mesh.generate(3), before any
    gmsh.model.mesh.setOrder(2): triangles must stay flat (3-node) for this,
    since it is for visualization only, not for the Elmer/Garfield++ solve.
    """
    node_tags, node_coords_flat, _ = gmsh.model.mesh.getNodes()
    vertices = np.array(node_coords_flat).reshape(-1, 3)
    tag_to_index = {tag: i for i, tag in enumerate(node_tags)}

    # 2 is Gmsh's element type code for a 3-node (flat, first-order) triangle.
    FLAT_TRIANGLE_TYPE = 2

    groups: dict[str, list[list[int]]] = {}
    for name, group_id in surface_group_ids.items():
        faces: list[list[int]] = []
        for surface_tag in gmsh.model.getEntitiesForPhysicalGroup(2, group_id):
            elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(2, surface_tag)
            for etype, node_tags_for_type in zip(elem_types, elem_node_tags):
                if etype != FLAT_TRIANGLE_TYPE:
                    continue
                triangles = np.array(node_tags_for_type).reshape(-1, 3)
                faces.extend(
                    [tag_to_index[a], tag_to_index[b], tag_to_index[c]]
                    for a, b, c in triangles
                )
        groups[name] = faces

    with open(output_path, "w") as f:
        json.dump({"vertices": vertices.tolist(), "groups": groups}, f)
