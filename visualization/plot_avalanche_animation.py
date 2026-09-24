"""Time-animated GIF of one avalanche event's electron cloud growing through
the 3-GEM stack, in 3D and as a side (x-z cross-section) view -- built at
the user's request (2026-09-24, see docs/debugging_notes.md) to actually
*see* the cascade develop over time, complementing the static cross-section
PNGs from macros/view_gem_avalanche_cross_section.cpp.

Renders headless via matplotlib's Agg backend (no PyVista/VTK, so no
off-screen-GL dependency -- this dev environment has neither an X server
nor OSMesa, see docs/debugging_notes.md's PyVista verification notes).

GEM geometry (copper electrodes with their tiled hole pattern) is drawn as
flat z=const surfaces with the hole footprints masked out to NaN.
IMPORTANT gotcha hit building this: matplotlib 3D's default depth-sort
(computed_zorder=True) mis-orders multiple large overlapping flat surfaces
at different z, making the copper render as almost entirely dark/washed
out. Fixed by setting ax.computed_zorder = False and assigning an explicit
zorder per surface (see draw_gem_geometry).

Electron count panel: shows the actual live population at each instant
(rises as new electrons are born via further avalanche multiplication,
falls as they're absorbed/attached/exit) using each track's first/last
recorded time as a birth/death event and a proper step function -- not a
monotonic "ever created" count, which would hide how many are lost.

Usage:
    python3 plot_avalanche_animation.py <avalanche.root> <event> [label]
    label: text shown in the title (e.g. "1.15x voltage"); defaults to the
    root file's base name.
Output: results/img/<baseName>_event<N>_avalanche_{3d,side}.gif
"""

import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import uproot

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "geometry"))
from gem_unit_cell import hole_centers_tiled

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
VIEW_HALF_X, VIEW_HALF_Y = 360.0, 620.0  # um -- covers the full tiled domain
Z_MIN, Z_MAX = -0.2029, 0.430  # cm -- GND up to just above GEM1
_GRID_N = 320


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


def _style_3d_axes(ax, view: str):
    ax.set_xlim(-VIEW_HALF_X, VIEW_HALF_X)
    ax.set_ylim(-VIEW_HALF_Y, VIEW_HALF_Y)
    ax.set_zlim(Z_MIN, Z_MAX)
    ax.set_xlabel("x [um]", color="white")
    ax.set_ylabel("y [um]", color="white")
    ax.set_zlabel("z [cm]", color="white")
    if view == "perspective":
        ax.view_init(elev=10, azim=50)
    else:  # side / cross-section-like view, looking along y
        ax.set_proj_type("ortho")
        ax.view_init(elev=4, azim=-90)  # small nonzero elev: exactly edge-on (elev=0)
        ax.set_yticklabels([])          # makes mplot3d's depth-sort degenerate/vanish
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


def render(view: str, out_path: str, x, y, z, t, alive_times, alive_cum,
           label: str, n_frames: int = 100, fps: int = 20, age_window_ns: float = 40.0):
    holes_um = [(hx * 1e4, hy * 1e4) for hx, hy in hole_centers_tiled(0.014, 5, 5)]
    holes_arr = np.array(holes_um)
    gx = np.linspace(-VIEW_HALF_X, VIEW_HALF_X, _GRID_N)
    gy = np.linspace(-VIEW_HALF_Y, VIEW_HALF_Y, _GRID_N)
    GX, GY = np.meshgrid(gx, gy)

    t_max = t.max()
    # Dense frames near t=0 (entry into GEM1 + initial multiplication happen
    # fast and are the most information-dense part), coarser later.
    frac = np.linspace(0, 1, n_frames)
    frame_times = t_max * frac**1.6

    fig = plt.figure(figsize=(7.2, 10.5))
    fig.patch.set_facecolor("black")
    gs = fig.add_gridspec(5, 1, height_ratios=[4, 4, 4, 0.15, 1.1], hspace=0.05)
    ax = fig.add_subplot(gs[0:3, 0], projection="3d")
    ax_count = fig.add_subplot(gs[4, 0])

    _style_3d_axes(ax, view)
    _draw_gem_geometry(ax, GX, GY, holes_arr)

    ax_count.set_facecolor("black")
    ax_count.set_xlim(0, t_max)
    ax_count.set_ylim(0, alive_cum.max() * 1.15)  # headroom so the peak isn't flush with the top
    ax_count.set_xlabel("t [ns]", color="white")
    ax_count.set_ylabel("electron count", color="white")
    ax_count.tick_params(colors="white")
    for spine in ax_count.spines.values():
        spine.set_color("white")

    title = ax.set_title("", color="white")
    alive_line, = ax_count.plot([], [], color=ELECTRON_COLOR, lw=2.0, drawstyle="steps-post")
    marker, = ax_count.plot([], [], "o", color=ELECTRON_COLOR, ms=5)
    scatter_holder = {"artist": None}

    def draw_frame(i):
        T = frame_times[i]
        sel = t <= T
        age = np.clip((T - t[sel]) / age_window_ns, 0.0, 1.0)
        alpha = (1.0 - age) * 0.85 + 0.05
        colors = np.tile(ELECTRON_COLOR, (sel.sum(), 1))
        rgba = np.concatenate([colors, alpha[:, None]], axis=1)
        size = 3.0 + 4.0 * (1.0 - age)
        if scatter_holder["artist"] is not None:
            scatter_holder["artist"].remove()
        scatter_holder["artist"] = ax.scatter(
            x[sel], y[sel], z[sel], c=rgba, s=size, linewidths=0, depthshade=False, zorder=100)
        title.set_text(f"{label}: t = {T:6.1f} / {t_max:.1f} ns")

        idx_alive = int(np.searchsorted(alive_times, T, side="right"))
        n_alive = int(alive_cum[idx_alive - 1]) if idx_alive > 0 else 0
        alive_line.set_data(
            np.concatenate([[0.0], alive_times[:idx_alive]]),
            np.concatenate([[0.0], alive_cum[:idx_alive]]),
        )
        marker.set_data([T], [n_alive])
        ax_count.set_title(f"{n_alive} electrons", color=ELECTRON_COLOR, fontsize=10)
        return (scatter_holder["artist"],)

    from matplotlib.animation import FuncAnimation, PillowWriter

    anim = FuncAnimation(fig, draw_frame, frames=n_frames, blit=False)
    anim.save(out_path, writer=PillowWriter(fps=fps))
    plt.close(fig)
    print(f"wrote {out_path}")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: plot_avalanche_animation.py <avalanche.root> <event> [label]")
        sys.exit(1)
    root_path = sys.argv[1]
    event = int(sys.argv[2])
    base_name = os.path.splitext(os.path.basename(root_path))[0].removesuffix("_avalanche")
    label = sys.argv[3] if len(sys.argv) > 3 else base_name

    os.makedirs(IMG_DIR, exist_ok=True)
    x, y, z, t, track = _load_event(root_path, event)
    alive_times, alive_cum = _birth_death_step(t, track)

    render("perspective", os.path.join(IMG_DIR, f"{base_name}_event{event}_avalanche_3d.gif"),
           x, y, z, t, alive_times, alive_cum, label)
    render("side", os.path.join(IMG_DIR, f"{base_name}_event{event}_avalanche_side.gif"),
           x, y, z, t, alive_times, alive_cum, label)


if __name__ == "__main__":
    main()
