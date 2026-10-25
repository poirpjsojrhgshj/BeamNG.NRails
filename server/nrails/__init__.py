"""BeamNG.NRails: everything the fork adds to BeamNG.Earth lives in this package.

Upstream's files only carry short hooks, each marked "# NRails hook", that call into nrails.hooks. Merging a new
upstream release is then a plain merge: the hooks are the only lines to look at when one conflicts (NRAILS.md,
"Upstream merges").

    nrails.paths     the download cache's real folder (junctions resolved)
    nrails.rails     the railway track of a road tile (meshes, collision, level crossings, tunnels, snap lines)
    nrails.bridges   approach slabs past the road bridges' abutments
    nrails.profile   the road classes' profile limits (grade, smoothing)
    nrails.hooks     the functions upstream's hooks call
"""
VERSION = "0.3.0"
