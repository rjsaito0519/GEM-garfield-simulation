"""Time-animated GIF of one avalanche event's electron cloud growing through
the 3-GEM stack, in 3D and as a side (x-z cross-section) view -- lets you
actually *see* the cascade develop over time, complementing the static
cross-section PNGs from macros/view_gem_avalanche_cross_section.cpp.

Renders headless via matplotlib's Agg backend (no PyVista/VTK, so no
off-screen-GL dependency -- this dev environment has neither an X server
nor OSMesa).

GEM geometry (copper electrodes with their tiled hole pattern) is drawn as
flat z=const surfaces with the hole footprints masked out to NaN.
matplotlib 3D's default depth-sort (computed_zorder=True) mis-orders
multiple large overlapping flat surfaces at different z, making the
copper render as almost entirely dark/washed out; worked around by setting
ax.computed_zorder = False and assigning an explicit zorder per surface
(see _draw_gem_geometry).

Electron count panel: shows the actual live population at each instant
(rises as new electrons are born via further avalanche multiplication,
falls as they're absorbed/attached/exit) using each track's first/last
recorded time as a birth/death event and a proper step function -- not a
monotonic "ever created" count, which would hide how many are lost.

Usage:
    python3 plot_avalanche_animation.py <avalanche.root> <event> [label] [--readme-demo]
    label: text shown in the title (e.g. "1.15x voltage"); defaults to the
    root file's base name.
    --readme-demo: also copy the rendered GIF to results/img/avalanche_demo.gif
    -- the fixed filename README.md embeds on GitHub's repo front page.
    That filename deliberately never changes so a better event found later
    can just be re-rendered with this flag to replace it in place, without
    touching README.md at all. This is the *only* GIF this project tracks
    in git (see .gitignore) -- every other rendered animation, including
    the plain <baseName>_event<N>_avalanche.gif this script always writes,
    stays untracked like the rest of results/.
Output: results/img/<baseName>_event<N>_avalanche.gif -- one combined
    animation, oblique and true side-on (elev=0) 3D panels side by side,
    sharing one electron-count panel below.
"""

import json
import os
import shutil
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import uproot

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "geometry"))
from gem_unit_cell import hole_centers_tiled
from analyze_plane_crossings import read_run_info

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(REPO_ROOT, "results", "img")

# triple_gem_field's GEM z-bounds/hole radii (see triple_gem_field_model.py /
# gem_params.py) -- hardcoded here since this script targets that one stack
# geometry specifically, not made geometry-agnostic like the PyVista viewer.
GEMS = [
    dict(z_top=0.4205, z_bot=0.4087, r_in=17.5, r_out=32.5, name="GEM1"),
    dict(z_top=0.2087, z_bot=0.2029, r_in=12.5, r_out=27.5, name="GEM2"),
    dict(z_top=0.0029, z_bot=-0.0029, r_in=12.5, r_out=27.5, name="GEM3"),
]
CU_COLOR = "#d98a3d"
DIEL_COLOR = "#241a0d"
ELECTRON_COLOR = np.array([1.0, 0.92, 0.15])
# Fallback only, for a file with no run-info tree to read the real tiled
# domain from (see _load_view_extent) -- matches this project's original
# 5x5-tiling default, from before wider convergence-check tilings (7x7,
# 9x9) were introduced.
_DEFAULT_VIEW_HALF_X, _DEFAULT_VIEW_HALF_Y = 360.0, 620.0  # um
_DEFAULT_PITCH_CM, _DEFAULT_N_CELLS = 0.014, 5
Z_MIN, Z_MAX = -0.2029, 0.430  # cm -- GND up to just above GEM1
_GRID_N = 320


def _load_view_extent(root_path: str):
    """(view_half_x_um, view_half_y_um, pitch_cm, n_cells_x, n_cells_y),
    read from this file's own run-info tree's "model_info_json" entry
    instead of the fixed 5x5-tiling defaults above -- those leave the view
    window (and the drawn GEM hole pattern) too narrow for a wider tiling
    like 7x7/9x9, visibly clipping electrons at the frame edges (for one
    9x9 event, ~20% of its x-points and ~11% of its y-points fell outside
    the old +-360/+-620um window). Falls back to those defaults, with a
    warning, for an older file with no run-info tree or no "geometry"
    half-extent in it.
    """
    with uproot.open(root_path) as f:
        run_info = read_run_info(f)
    if run_info and "model_info_json" in run_info:
        g = json.loads(run_info["model_info_json"])["geometry"]
        if all(k in g for k in ("half_extent_x_cm", "half_extent_y_cm", "pitch_cm",
                                 "n_cells_x", "n_cells_y")):
            return (g["half_extent_x_cm"] * 1e4, g["half_extent_y_cm"] * 1e4,
                    g["pitch_cm"], g["n_cells_x"], g["n_cells_y"])
    print(f"WARNING: {root_path} has no usable run-info geometry -- falling back to the "
          f"default 5x5-tiling view window (+-{_DEFAULT_VIEW_HALF_X:.0f}/"
          f"+-{_DEFAULT_VIEW_HALF_Y:.0f}um), which may be too narrow/wrong for this file's "
          "actual tiling and clip or mis-draw electrons near the edges.")
    return (_DEFAULT_VIEW_HALF_X, _DEFAULT_VIEW_HALF_Y, _DEFAULT_PITCH_CM,
            _DEFAULT_N_CELLS, _DEFAULT_N_CELLS)


def _hole_mask(GX, GY, holes_arr, radius_um):
    d2 = (GX[..., None] - holes_arr[:, 0]) ** 2 + (GY[..., None] - holes_arr[:, 1]) ** 2
    return (d2 < radius_um**2).any(axis=-1)


def _draw_gem_geometry(ax, GX, GY, holes_arr):
    # mplot3d's automatic depth-sort (computed_zorder) mis-orders multiple
    # large overlapping flat surfaces at different z -- disable it and
    # assign an explicit zorder per surface (lowest GEM first) instead.
    ax.computed_zorder = False
    for zo, gem in enumerate(reversed(GEMS)):
        mask_out = _hole_mask(GX, GY, holes_arr, gem["r_out"])
        Z_top = np.where(mask_out, np.nan, gem["z_top"])
        Z_bot = np.where(mask_out, np.nan, gem["z_bot"])
        ax.plot_surface(GX, GY, Z_top, color=CU_COLOR, shade=False, linewidth=0,
                         antialiased=False, zorder=zo * 3)
        ax.plot_surface(GX, GY, Z_bot, color=CU_COLOR, shade=False, linewidth=0,
                         antialiased=False, zorder=zo * 3 + 1)
        mask_in = _hole_mask(GX, GY, holes_arr, gem["r_in"])
        Z_mid = np.where(mask_in, np.nan, (gem["z_top"] + gem["z_bot"]) / 2.0)
        ax.plot_surface(GX, GY, Z_mid, color=DIEL_COLOR, shade=False, linewidth=0,
                         antialiased=False, zorder=zo * 3 + 0.5)


def _style_3d_axes(ax, view: str, view_half_x: float, view_half_y: float):
    ax.set_xlim(-view_half_x, view_half_x)
    ax.set_ylim(-view_half_y, view_half_y)
    ax.set_zlim(Z_MIN, Z_MAX)
    ax.set_xlabel("x [um]", color="white")
    ax.set_ylabel("y [um]", color="white")
    ax.set_zlabel("z [cm]", color="white")
    if view == "perspective":
        ax.view_init(elev=10, azim=50)
    else:  # side / cross-section-like view, looking directly along y
        ax.set_proj_type("ortho")
        # Exactly edge-on (elev=0) makes mplot3d's depth-sort degenerate --
        # the GEM copper/dielectric surfaces render mostly invisible instead
        # of properly layered (see module docstring's computed_zorder note;
        # this is a further, separate mplot3d quirk at elev=0 specifically).
        # A small nonzero elev (e.g. 4) would avoid that, at the cost of not
        # being a true side-on projection. This uses elev=0 for a genuine
        # side view -- the GEM structure isn't visible here as a result, but
        # the side-by-side perspective panel still shows it, so nothing is
        # lost overall.
        ax.view_init(elev=0, azim=-90)
        ax.set_yticklabels([])  # y is the (hidden) depth axis in this view
    ax.set_facecolor("black")
    ax.xaxis.pane.set_facecolor((0, 0, 0, 1))
    ax.yaxis.pane.set_facecolor((0, 0, 0, 1))
    ax.zaxis.pane.set_facecolor((0, 0, 0, 1))
    ax.tick_params(colors="white")


def _load_event(root_path: str, event: int):
    with uproot.open(root_path) as f:
        data = f["Trajectories"].arrays(["event", "track", "x", "y", "z", "t"], library="np")
    m = data["event"] == event
    if not m.any():
        raise ValueError(f"No such event {event} in {root_path}")
    x, y, z, t, track = (data[k][m] for k in ["x", "y", "z", "t", "track"])
    return x * 1e4, y * 1e4, z, t, track


def _birth_death_step(t: np.ndarray, track: np.ndarray):
    """Per-track first/last recorded time -> a step function of the live
    population vs time (rises on birth, falls on death)."""
    birth_t, death_t = {}, {}
    for tr, ti in zip(track, t):
        if tr not in birth_t or ti < birth_t[tr]:
            birth_t[tr] = ti
        if tr not in death_t or ti > death_t[tr]:
            death_t[tr] = ti
    births = np.array(sorted(birth_t.values()))
    deaths = np.array(sorted(death_t.values()))
    event_times = np.concatenate([births, deaths])
    event_deltas = np.concatenate([np.ones_like(births), -np.ones_like(deaths)])
    order = np.argsort(event_times, kind="stable")
    alive_times = event_times[order]
    alive_cum = np.cumsum(event_deltas[order])
    return alive_times, alive_cum


def render(out_path: str, x, y, z, t, alive_times, alive_cum, label: str,
           view_half_x: float, view_half_y: float, pitch_cm: float, n_cells_x: int, n_cells_y: int,
           n_frames: int = 100, fps: int = 20, age_window_ns: float = 40.0):
    """One combined GIF: perspective (oblique) and true side-on (elev=0)
    3D panels side by side, sharing one electron-count panel below, so the
    oblique and side views can be compared directly without needing the
    GEM structure to stay visible in the side view.

    view_half_x/y, pitch_cm, n_cells_x/y: this event's actual tiled-domain
    extent and hole pattern (see _load_view_extent) -- NOT a fixed 5x5
    assumption, which clips electrons at the frame edges for a wider
    tiling like 9x9."""
    holes_um = [(hx * 1e4, hy * 1e4) for hx, hy in hole_centers_tiled(pitch_cm, n_cells_x, n_cells_y)]
    holes_arr = np.array(holes_um)
    gx = np.linspace(-view_half_x, view_half_x, _GRID_N)
    gy = np.linspace(-view_half_y, view_half_y, _GRID_N)
    GX, GY = np.meshgrid(gx, gy)

    t_max = t.max()
    # Dense frames near BOTH ends of the timeline, coarser in the middle:
    # t=0 (entry into GEM1 + initial multiplication happen fast) needs dense
    # sampling, and so does the tail end (what happens after the cloud
    # clears GEM3, into the induction gap -- a dense-near-zero-only skew
    # makes that part feel rushed and cut short). The typical per-event
    # time profile is a multiplication burst, a quiet decay stretch, then
    # another burst near the next GEM -- the quiet stretches are the least
    # visually interesting part, so that's where frames can be sparse. A
    # smoothstep g(frac) = 3*frac^2 - 2*frac^3 has g'(0)=g'(1)=0
    # (time barely advances per frame near either end -- i.e. dense sampling
    # there) and its steepest slope at frac=0.5 (time advances fastest
    # there -- sparse sampling in the middle), giving exactly that shape.
    frac = np.linspace(0, 1, n_frames)
    frame_times = t_max * (3.0 * frac**2 - 2.0 * frac**3)

    fig = plt.figure(figsize=(13.0, 7.6))
    fig.patch.set_facecolor("black")
    gs = fig.add_gridspec(2, 2, height_ratios=[5.5, 1.3], hspace=0.10, wspace=0.02)
    ax_persp = fig.add_subplot(gs[0, 0], projection="3d")
    ax_side = fig.add_subplot(gs[0, 1], projection="3d")
    ax_count = fig.add_subplot(gs[1, :])

    _style_3d_axes(ax_persp, "perspective", view_half_x, view_half_y)
    _style_3d_axes(ax_side, "side", view_half_x, view_half_y)
    _draw_gem_geometry(ax_persp, GX, GY, holes_arr)
    _draw_gem_geometry(ax_side, GX, GY, holes_arr)

    ax_count.set_facecolor("black")
    ax_count.set_xlim(0, t_max)
    ax_count.set_ylim(0, alive_cum.max() * 1.15)  # headroom so the peak isn't flush with the top
    ax_count.set_xlabel("t [ns]", color="white")
    ax_count.set_ylabel("electron count", color="white")
    ax_count.tick_params(colors="white")
    for spine in ax_count.spines.values():
        spine.set_color("white")

    title = fig.suptitle("", color="white", y=0.98)
    ax_persp.set_title("oblique", color="white", fontsize=9, y=0.97)
    ax_side.set_title("side (x-z)", color="white", fontsize=9, y=0.97)
    alive_line, = ax_count.plot([], [], color=ELECTRON_COLOR, lw=2.0, drawstyle="steps-post")
    marker, = ax_count.plot([], [], "o", color=ELECTRON_COLOR, ms=5)
    scatter_holders = {"persp": None, "side": None}

    def draw_frame(i):
        T = frame_times[i]
        sel = t <= T
        age = np.clip((T - t[sel]) / age_window_ns, 0.0, 1.0)
        alpha = (1.0 - age) * 0.85 + 0.05
        colors = np.tile(ELECTRON_COLOR, (sel.sum(), 1))
        rgba = np.concatenate([colors, alpha[:, None]], axis=1)
        size = 3.0 + 4.0 * (1.0 - age)
        for key, ax_obj in (("persp", ax_persp), ("side", ax_side)):
            if scatter_holders[key] is not None:
                scatter_holders[key].remove()
            scatter_holders[key] = ax_obj.scatter(
                x[sel], y[sel], z[sel], c=rgba, s=size, linewidths=0,
                depthshade=False, zorder=100)
        title.set_text(f"{label}: t = {T:6.1f} / {t_max:.1f} ns")

        idx_alive = int(np.searchsorted(alive_times, T, side="right"))
        n_alive = int(alive_cum[idx_alive - 1]) if idx_alive > 0 else 0
        # Always extend the line's last point out to the current frame time
        # T (not just to the last actual birth/death event before T) --
        # without this, drawstyle="steps-post" only draws up to whatever
        # event time happens to precede T, so during any stretch where the
        # population doesn't change the line visibly stops short of the
        # current time and then jumps forward once the next event finally
        # occurs, looking like a broken/reconnecting line. The count is
        # unchanged during that stretch, but a point still belongs at
        # (T, n_alive) so the line is continuous.
        alive_line.set_data(
            np.concatenate([[0.0], alive_times[:idx_alive], [T]]),
            np.concatenate([[0.0], alive_cum[:idx_alive], [n_alive]]),
        )
        marker.set_data([T], [n_alive])
        ax_count.set_title(f"{n_alive} electrons", color=ELECTRON_COLOR, fontsize=10)
        return tuple(scatter_holders.values())

    from matplotlib.animation import FuncAnimation, PillowWriter

    anim = FuncAnimation(fig, draw_frame, frames=n_frames, blit=False)
    anim.save(out_path, writer=PillowWriter(fps=fps))
    plt.close(fig)
    print(f"wrote {out_path}")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--readme-demo"]
    set_as_readme_demo = "--readme-demo" in sys.argv[1:]
    if len(args) < 2:
        print("Usage: plot_avalanche_animation.py <avalanche.root> <event> [label] [--readme-demo]")
        sys.exit(1)
    root_path = args[0]
    event = int(args[1])
    base_name = os.path.splitext(os.path.basename(root_path))[0].removesuffix("_avalanche")
    label = args[2] if len(args) > 2 else base_name

    os.makedirs(IMG_DIR, exist_ok=True)
    x, y, z, t, track = _load_event(root_path, event)
    alive_times, alive_cum = _birth_death_step(t, track)
    view_half_x, view_half_y, pitch_cm, n_cells_x, n_cells_y = _load_view_extent(root_path)

    out_path = os.path.join(IMG_DIR, f"{base_name}_event{event}_avalanche.gif")
    render(out_path, x, y, z, t, alive_times, alive_cum, label,
           view_half_x, view_half_y, pitch_cm, n_cells_x, n_cells_y)

    if set_as_readme_demo:
        demo_path = os.path.join(IMG_DIR, "avalanche_demo.gif")
        shutil.copyfile(out_path, demo_path)
        print(f"--readme-demo: copied to {demo_path} (README.md's tracked front-page GIF)")


if __name__ == "__main__":
    main()
