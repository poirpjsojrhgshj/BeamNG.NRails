//! GPU compute (the user, 2026-10-22: "the CPU has a lot of work, so moving any work to the gpu will help a lot"):
//! a headless wgpu device made on first use (Vulkan, DX12 or Metal: whatever the machine has; none -> the callers
//! keep their CPU path), and the kernels that run on it.
//!
//! seam_detect: colormatch.detect_seams' oriented step filter over all its angles (the 36 rotations, the box sums,
//! the segment medians, the agreement and the S2 gate, the rotation back and the best angle per cell), which was ~10
//! s of CPU per colour-match region (the rotations in PIL, earthfast.seam_pass per angle). The same geometry as the
//! CPU path (PIL's rotate with expand, bilinear, zero outside; the box and band sums; the lower medians), in float32:
//! close to the CPU path's results, not bit-identical (the CPU path's sums are float64), and the same on one machine
//! every time.

use std::sync::{Mutex, OnceLock};

use wgpu::util::DeviceExt;

pub struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    pub name: String,
    seam: Mutex<Option<SeamPipes>>,
}

static GPU: OnceLock<Option<Gpu>> = OnceLock::new();

/// The device (made on first use), or None where there is no usable GPU (BNGE_GPU=0 turns it off).
pub fn get() -> Option<&'static Gpu> {
    GPU.get_or_init(|| {
        if std::env::var("BNGE_GPU").map(|v| v == "0").unwrap_or(false) {
            return None;
        }
        // (a driver's panic must not take the server down: no GPU, the CPU paths)
        std::panic::catch_unwind(|| pollster::block_on(init())).ok().flatten()
    })
    .as_ref()
}

async fn init() -> Option<Gpu> {
    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
        backends: wgpu::Backends::VULKAN | wgpu::Backends::DX12 | wgpu::Backends::METAL,
        ..Default::default()
    });
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
        })
        .await
        .ok()?;
    let info = adapter.get_info();
    if info.device_type == wgpu::DeviceType::Cpu {
        return None; // (a software rasteriser: no faster than the CPU path)
    }
    let mut limits = wgpu::Limits::default();
    let al = adapter.limits();
    limits.max_storage_buffer_binding_size = al.max_storage_buffer_binding_size;
    limits.max_buffer_size = al.max_buffer_size;
    let (device, queue) = adapter
        .request_device(&wgpu::DeviceDescriptor {
            label: Some("earthfast"),
            required_features: wgpu::Features::empty(),
            required_limits: limits,
            memory_hints: wgpu::MemoryHints::Performance,
            trace: wgpu::Trace::Off,
        })
        .await
        .ok()?;
    Some(Gpu { device, queue, name: format!("{} ({:?})", info.name, info.backend), seam: Mutex::new(None) })
}

// --- seam_detect -----------------------------------------------------------------------------------------------

const SEAM_WGSL: &str = r#"
struct P {
    w: u32, h: u32, wr: u32, hr: u32,
    half: i32, depth: i32, nseg: u32, min_valid: u32,
    full: f32, gate: f32, agree: f32, ang: f32,
    // forward: rotated pixel -> source (orig) coordinates; back: orig pixel (+ crop) -> rotated coordinates
    fa: f32, fb: f32, fc: f32, fd: f32, fe: f32, ff: f32, cx: f32, cy: f32,
    ba: f32, bb: f32, bc: f32, bd: f32, be: f32, bf: f32, bw: f32, bh: f32,
    offs: array<vec4<i32>, 2>,
};
@group(0) @binding(0) var<uniform> p: P;
@group(0) @binding(1) var<storage, read> src: array<f32>;          // 7 x h x w
@group(0) @binding(2) var<storage, read_write> rot: array<f32>;    // 7 x hr x wr
@group(0) @binding(3) var<storage, read_write> hs: array<f32>;     // 7 x hr x wr
@group(0) @binding(4) var<storage, read_write> dseg: array<f32>;   // 6 x hr x wr
@group(0) @binding(5) var<storage, read_write> okb: array<u32>;    // hr x wr
@group(0) @binding(6) var<storage, read_write> res: array<f32>;    // 4 x hr x wr: score, Dm r g b
@group(0) @binding(7) var<storage, read_write> outb: array<f32>;   // 5 x h x w: best, ang, D r g b

fn off(k: u32) -> i32 { return p.offs[k / 4u][k % 4u]; }

// PIL's bilinear filter for "F" images (libImaging Geometry.c): 0 outside, edges clamped, the next row only when in.
fn pil_bilinear(base: u32, W: i32, H: i32, xin: f32, yin: f32, fromsrc: bool) -> f32 {
    if (xin < 0.0 || xin >= f32(W) || yin < 0.0 || yin >= f32(H)) { return 0.0; }
    let x = xin - 0.5; let y = yin - 0.5;
    let xf = floor(x); let yf = floor(y);
    let dx = x - xf; let dy = y - yf;
    let xi = i32(xf); let yi = i32(yf);
    let x0 = clamp(xi, 0, W - 1); let x1 = clamp(xi + 1, 0, W - 1);
    let y0 = clamp(yi, 0, H - 1);
    var a0: f32; var a1: f32;
    if (fromsrc) { a0 = src[base + u32(y0 * W + x0)]; a1 = src[base + u32(y0 * W + x1)]; }
    else { a0 = res[base + u32(y0 * W + x0)]; a1 = res[base + u32(y0 * W + x1)]; }
    let v1 = a0 + (a1 - a0) * dx;
    var v2 = v1;
    if (yi + 1 >= 0 && yi + 1 < H) {
        var b0: f32; var b1: f32;
        if (fromsrc) { b0 = src[base + u32((yi + 1) * W + x0)]; b1 = src[base + u32((yi + 1) * W + x1)]; }
        else { b0 = res[base + u32((yi + 1) * W + x0)]; b1 = res[base + u32((yi + 1) * W + x1)]; }
        v2 = b0 + (b1 - b0) * dx;
    }
    return v1 + (v2 - v1) * dy;
}

@compute @workgroup_size(16, 16)
fn rotate(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= p.wr || g.y >= p.hr) { return; }
    let x = f32(g.x) + 0.5; let y = f32(g.y) + 0.5;
    let xs = p.fa * x + p.fb * y + p.fc;
    let ys = p.fd * x + p.fe * y + p.ff;
    let n = p.wr * p.hr; let ns = p.w * p.h;
    for (var c = 0u; c < 7u; c++) {
        rot[c * n + g.y * p.wr + g.x] = pil_bilinear(c * ns, i32(p.w), i32(p.h), xs, ys, true);
    }
}

@compute @workgroup_size(16, 16)
fn hsum(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= p.wr || g.y >= p.hr) { return; }
    let n = p.wr * p.hr;
    let x0 = max(i32(g.x) - p.half, 0); let x1 = min(i32(g.x) + p.half, i32(p.wr) - 1);
    for (var c = 0u; c < 7u; c++) {
        var s = 0.0;
        let row = c * n + g.y * p.wr;
        for (var x = x0; x <= x1; x++) { s += rot[row + u32(x)]; }
        hs[row + g.x] = s;
    }
}

fn band(c: u32, x: u32, y0: i32, y1: i32) -> f32 {   // rows [y0, y1) clipped, of hs channel c
    let n = p.wr * p.hr;
    var s = 0.0;
    for (var y = max(y0, 0); y < min(y1, i32(p.hr)); y++) { s += hs[c * n + u32(y) * p.wr + x]; }
    return s;
}

@compute @workgroup_size(16, 16)
fn bands(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= p.wr || g.y >= p.hr) { return; }
    let n = p.wr * p.hr; let i = g.y * p.wr + g.x; let j = i32(g.y);
    let wb = band(0u, g.x, j + 1, j + p.depth + 1);
    let wa = band(0u, g.x, j - p.depth, j);
    var ok = 0u;
    if (wb > p.full && wa > p.full) { ok = 1u; }
    okb[i] = ok;
    let ib = 1.0 / max(wb, 1e-3); let ia = 1.0 / max(wa, 1e-3);
    for (var c = 0u; c < 6u; c++) {
        dseg[c * n + i] = band(c + 1u, g.x, j + 1, j + p.depth + 1) * ib - band(c + 1u, g.x, j - p.depth, j) * ia;
    }
}

// the lower median of the ok values among v[0..k) (colormatch._vmedian; 0 when none)
fn lower_median(v: array<f32, 8>, ok: array<bool, 8>, k: u32, nvalid: u32) -> f32 {
    if (nvalid == 0u) { return 0.0; }
    var b: array<f32, 8>;
    var m = 0u;
    for (var i = 0u; i < k; i++) { if (ok[i]) { b[m] = v[i]; m++; } }
    for (var i = 1u; i < m; i++) {          // insertion sort (k <= 8)
        let x = b[i]; var j = i;
        while (j > 0u && b[j - 1u] > x) { b[j] = b[j - 1u]; j--; }
        b[j] = x;
    }
    return b[(nvalid - 1u) / 2u];
}

@compute @workgroup_size(16, 16)
fn segs(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= p.wr || g.y >= p.hr) { return; }
    let n = p.wr * p.hr; let i = g.y * p.wr + g.x;
    var oks: array<bool, 8>;
    var dl: array<vec3<f32>, 8>;
    var ds: array<vec3<f32>, 8>;
    var nvalid = 0u;
    for (var k = 0u; k < p.nseg; k++) {
        let xs = i32(g.x) + off(k);
        oks[k] = false; dl[k] = vec3<f32>(0.0); ds[k] = vec3<f32>(0.0);
        if (xs >= 0 && xs < i32(p.wr)) {
            let q = g.y * p.wr + u32(xs);
            oks[k] = okb[q] == 1u;
            let su = vec3<f32>(dseg[q], dseg[n + q], dseg[2u * n + q]);
            let s2 = vec3<f32>(dseg[3u * n + q], dseg[4u * n + q], dseg[5u * n + q]);
            dl[k] = su - s2; ds[k] = s2;
        }
        if (oks[k]) { nvalid++; }
    }
    var m = vec3<f32>(0.0); var msm = vec3<f32>(0.0);
    for (var c = 0u; c < 3u; c++) {
        var a: array<f32, 8>; var b: array<f32, 8>;
        for (var k = 0u; k < p.nseg; k++) { a[k] = dl[k][c]; b[k] = ds[k][c]; }
        m[c] = lower_median(a, oks, p.nseg, nvalid);
        msm[c] = lower_median(b, oks, p.nseg, nvalid);
    }
    let nm = length(m);
    var agree = 0u;
    for (var k = 0u; k < p.nseg; k++) {
        let nk = length(dl[k]);
        let cs = dot(dl[k], m) / max(nk * nm, 1e-6);
        if (cs > 0.7 && nk > 0.5 * nm && oks[k]) { agree++; }
    }
    let cons = nvalid >= p.min_valid && f32(agree) >= p.agree * f32(nvalid);
    let nsm = length(msm);
    let gt = clamp(1.0 - max(nsm - 0.03, 0.0) / (p.gate * nm + 1e-3), 0.0, 1.0);
    var sc = 0.0;
    if (cons) { sc = nm * gt; }
    res[i] = sc;
    res[n + i] = m.x; res[2u * n + i] = m.y; res[3u * n + i] = m.z;
}

@compute @workgroup_size(16, 16)
fn unrot(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= p.w || g.y >= p.h) { return; }
    let x = f32(g.x) + p.cx + 0.5; let y = f32(g.y) + p.cy + 0.5;    // (in the back-rotated image, cropped)
    let xs = p.ba * x + p.bb * y + p.bc;
    let ys = p.bd * x + p.be * y + p.bf;
    let n = p.wr * p.hr; let no = p.w * p.h; let i = g.y * p.w + g.x;
    let sc = pil_bilinear(0u, i32(p.wr), i32(p.hr), xs, ys, false);
    if (sc > outb[i]) {
        outb[i] = sc;
        outb[no + i] = p.ang;
        for (var c = 0u; c < 3u; c++) {
            outb[(2u + c) * no + i] = pil_bilinear((1u + c) * n, i32(p.wr), i32(p.hr), xs, ys, false);
        }
    }
}
"#;

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct SeamParams {
    w: u32, h: u32, wr: u32, hr: u32,
    half: i32, depth: i32, nseg: u32, min_valid: u32,
    full: f32, gate: f32, agree: f32, ang: f32,
    fa: f32, fb: f32, fc: f32, fd: f32, fe: f32, ff: f32, cx: f32, cy: f32,
    ba: f32, bb: f32, bc: f32, bd: f32, be: f32, bf: f32, bw: f32, bh: f32,
    offs: [i32; 8],
}

struct SeamPipes {
    layout: wgpu::BindGroupLayout,
    pipes: [wgpu::ComputePipeline; 5],
}

fn seam_pipes(gpu: &Gpu) -> std::sync::MutexGuard<'_, Option<SeamPipes>> {
    let mut g = gpu.seam.lock().unwrap();
    if g.is_none() {
        let d = &gpu.device;
        let module = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("seam"),
            source: wgpu::ShaderSource::Wgsl(SEAM_WGSL.into()),
        });
        let entry = |b: u32, ty: wgpu::BufferBindingType| wgpu::BindGroupLayoutEntry {
            binding: b,
            visibility: wgpu::ShaderStages::COMPUTE,
            ty: wgpu::BindingType::Buffer { ty, has_dynamic_offset: false, min_binding_size: None },
            count: None,
        };
        let mut entries = vec![entry(0, wgpu::BufferBindingType::Uniform),
                               entry(1, wgpu::BufferBindingType::Storage { read_only: true })];
        for b in 2..8 {
            entries.push(entry(b, wgpu::BufferBindingType::Storage { read_only: false }));
        }
        let layout = d.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor { label: None, entries: &entries });
        let pl = d.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None, bind_group_layouts: &[&layout], push_constant_ranges: &[],
        });
        let mk = |ep: &str| d.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some(ep), layout: Some(&pl), module: &module, entry_point: Some(ep),
            compilation_options: Default::default(), cache: None,
        });
        *g = Some(SeamPipes { layout, pipes: [mk("rotate"), mk("hsum"), mk("bands"), mk("segs"), mk("unrot")] });
    }
    g
}

/// PIL's Image.rotate(deg, expand=True) for a w x h image: (the affine matrix from output pixel coordinates to the
/// input's, the output size), as Image.rotate computes them (float64, its rounding of cos / sin to 15 places).
fn pil_rotate(deg: f64, w: f64, h: f64) -> ([f64; 6], usize, usize) {
    let angle = -(deg % 360.0).to_radians();
    let r15 = |v: f64| (v * 1e15).round() / 1e15;
    let mut m = [r15(angle.cos()), r15(angle.sin()), 0.0, r15(-angle.sin()), r15(angle.cos()), 0.0];
    let t = |m: &[f64; 6], x: f64, y: f64| (m[0] * x + m[1] * y + m[2], m[3] * x + m[4] * y + m[5]);
    let (cx, cy) = (w / 2.0, h / 2.0);
    let (a, b) = t(&m, -cx, -cy);
    m[2] = a + cx;
    m[5] = b + cy;
    let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY);
    for (x, y) in [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)] {
        let (u, v) = t(&m, x, y);
        x0 = x0.min(u); x1 = x1.max(u); y0 = y0.min(v); y1 = y1.max(v);
    }
    let nw = x1.ceil() - x0.floor();
    let nh = y1.ceil() - y0.floor();
    let (a, b) = t(&m, -(nw - w) / 2.0, -(nh - h) / 2.0);
    m[2] = a;
    m[5] = b;
    (m, nw as usize, nh as usize)
}

/// colormatch.detect_seams' angle loop: src (7, h, w) float32 = [w, w*L_0 .. w*L_5]; returns (best, ang, D) as
/// flat float32 (h*w, h*w, 3*h*w), or an error string.
#[allow(clippy::too_many_arguments)]
pub fn seam_detect(gpu: &Gpu, src: &[f32], h: usize, w: usize, n_ang: usize, half: i32, depth: i32, offs: &[i32],
                   full: f32, gate: f32, agree: f32, min_valid: u32) -> Result<Vec<f32>, String> {
    if offs.len() > 8 || src.len() != 7 * h * w {
        return Err("seam_detect: bad arguments".into());
    }
    let d = &gpu.device;
    // the largest rotated size over the angles (at 45 deg)
    let (mut wr_max, mut hr_max) = (0usize, 0usize);
    let geo: Vec<_> = (0..n_ang).map(|k| {
        let deg = 180.0 * k as f64 / n_ang as f64;
        let (fwd, wr, hr) = pil_rotate(deg, w as f64, h as f64);
        let (back, w2, h2) = pil_rotate(-deg, wr as f64, hr as f64);
        wr_max = wr_max.max(wr);
        hr_max = hr_max.max(hr);
        (deg, fwd, wr, hr, back, w2, h2)
    }).collect();
    let nr = wr_max * hr_max;
    let buf = |label: &str, n: usize, usage: wgpu::BufferUsages| d.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label), size: (n * 4) as u64, usage, mapped_at_creation: false,
    });
    let st = wgpu::BufferUsages::STORAGE;
    let srcb = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("src"), contents: bytemuck::cast_slice(src), usage: st,
    });
    let rot = buf("rot", 7 * nr, st);
    let hs = buf("hs", 7 * nr, st);
    let dseg = buf("dseg", 6 * nr, st);
    let okb = buf("ok", nr, st);
    let res = buf("res", 4 * nr, st);
    let mut init_out = vec![0f32; 5 * h * w];
    for v in init_out[..h * w].iter_mut() {
        *v = 0.0; // best starts at 0: a score must exceed it (the CPU path's `score_o > best` from zeros)
    }
    let outb = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("out"), contents: bytemuck::cast_slice(&init_out), usage: st | wgpu::BufferUsages::COPY_SRC,
    });
    let pbuf = buf("params", std::mem::size_of::<SeamParams>() / 4, wgpu::BufferUsages::UNIFORM
                   | wgpu::BufferUsages::COPY_DST);
    let guard = seam_pipes(gpu);
    let sp = guard.as_ref().unwrap();
    let bg = d.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout: &sp.layout,
        entries: &[&pbuf, &srcb, &rot, &hs, &dseg, &okb, &res, &outb].iter().enumerate()
            .map(|(i, b)| wgpu::BindGroupEntry { binding: i as u32, resource: b.as_entire_binding() })
            .collect::<Vec<_>>(),
    });
    let mut o8 = [0i32; 8];
    o8[..offs.len()].copy_from_slice(offs);
    for (deg, fwd, wr, hr, back, w2, h2) in geo {
        let pr = SeamParams {
            w: w as u32, h: h as u32, wr: wr as u32, hr: hr as u32, half, depth, nseg: offs.len() as u32, min_valid,
            full, gate, agree, ang: deg.to_radians() as f32,
            fa: fwd[0] as f32, fb: fwd[1] as f32, fc: fwd[2] as f32, fd: fwd[3] as f32, fe: fwd[4] as f32,
            ff: fwd[5] as f32,
            cx: ((w2 - w) / 2) as f32, cy: ((h2 - h) / 2) as f32,
            ba: back[0] as f32, bb: back[1] as f32, bc: back[2] as f32, bd: back[3] as f32, be: back[4] as f32,
            bf: back[5] as f32, bw: w2 as f32, bh: h2 as f32,
            offs: o8,
        };
        gpu.queue.write_buffer(&pbuf, 0, bytemuck::bytes_of(&pr));
        let mut enc = d.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor { label: None, timestamp_writes: None });
            pass.set_bind_group(0, &bg, &[]);
            for (i, pipe) in sp.pipes.iter().enumerate() {
                let (gw, gh) = if i == 4 { (w, h) } else { (wr, hr) };
                pass.set_pipeline(pipe);
                pass.dispatch_workgroups(gw.div_ceil(16) as u32, gh.div_ceil(16) as u32, 1);
            }
        }
        gpu.queue.submit(Some(enc.finish()));
    }
    // read back
    let n_out = 5 * h * w;
    let rb = buf("readback", n_out, wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST);
    let mut enc = d.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
    enc.copy_buffer_to_buffer(&outb, 0, &rb, 0, (n_out * 4) as u64);
    gpu.queue.submit(Some(enc.finish()));
    let slice = rb.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |r| { let _ = tx.send(r); });
    d.poll(wgpu::PollType::Wait).map_err(|e| format!("poll: {e:?}"))?;
    rx.recv().map_err(|e| format!("map: {e}"))?.map_err(|e| format!("map: {e:?}"))?;
    let out = bytemuck::cast_slice::<u8, f32>(&slice.get_mapped_range()).to_vec();
    rb.unmap();
    Ok(out)
}

// --- bc1 -------------------------------------------------------------------------------------------------------

// earthfast.bc1_encode's block encoder (lib.rs bc1_block) in float32, one invocation per 4 x 4 block of any of the
// levels packed one after another: endpoints on the block's principal axis (power iteration), one least-squares
// refinement on the chosen indices, the better of the two, each texel the nearest of the 4 colours.
const BC1_WGSL: &str = r#"
struct Level { w: u32, h: u32, px: u32, nbx: u32, blk: u32, nblk: u32, _a: u32, _b: u32 };
@group(0) @binding(0) var<storage, read> lv: array<Level>;
@group(0) @binding(1) var<storage, read> pix: array<u32>;      // RGBA8 texels of every level
@group(0) @binding(2) var<storage, read_write> outb: array<u32>; // 2 words per block
@group(0) @binding(3) var<uniform> nlev: vec4<u32>;

fn to565(c: vec3<f32>) -> u32 {
    let k = clamp(c, vec3<f32>(0.0), vec3<f32>(255.0));
    let r = u32(floor(k.x * 31.0 / 255.0 + 0.5));
    let g = u32(floor(k.y * 63.0 / 255.0 + 0.5));
    let b = u32(floor(k.z * 31.0 / 255.0 + 0.5));
    return (r << 11u) | (g << 5u) | b;
}
fn rgb565(x: u32) -> vec3<i32> {
    let r = i32((x >> 11u) & 31u); let g = i32((x >> 5u) & 63u); let b = i32(x & 31u);
    return vec3<i32>((r << 3u) | (r >> 2u), (g << 2u) | (g >> 4u), (b << 3u) | (b >> 2u));
}

@compute @workgroup_size(64)
fn bc1(@builtin(global_invocation_id) gid: vec3<u32>) {
    let g = gid.x;
    var L = 0u;
    var found = false;
    for (var i = 0u; i < nlev.x; i++) {
        if (g >= lv[i].blk && g < lv[i].blk + lv[i].nblk) { L = i; found = true; }
    }
    if (!found) { return; }
    let l = lv[L];
    let b = g - l.blk;
    let by = b / l.nbx; let bx = b % l.nbx;
    var t: array<vec3<i32>, 16>;
    for (var yy = 0u; yy < 4u; yy++) {
        let y = min(by * 4u + yy, l.h - 1u);
        for (var xx = 0u; xx < 4u; xx++) {
            let x = min(bx * 4u + xx, l.w - 1u);
            let v = pix[l.px + y * l.w + x];
            t[yy * 4u + xx] = vec3<i32>(i32(v & 255u), i32((v >> 8u) & 255u), i32((v >> 16u) & 255u));
        }
    }
    var mean = vec3<f32>(0.0);
    for (var k = 0u; k < 16u; k++) { mean += vec3<f32>(t[k]) / 16.0; }
    var cov = mat3x3<f32>(vec3<f32>(0.0), vec3<f32>(0.0), vec3<f32>(0.0));
    for (var k = 0u; k < 16u; k++) {
        let d = vec3<f32>(t[k]) - mean;
        cov[0] += d * d.x; cov[1] += d * d.y; cov[2] += d * d.z;
    }
    var v = vec3<f32>(0.577, 0.577, 0.577);
    for (var it = 0; it < 6; it++) {
        let w = cov * v;
        let n = length(w);
        if (n < 1e-9) { break; }
        v = w / n;
    }
    var pmin = 1e30; var pmax = -1e30;
    for (var k = 0u; k < 16u; k++) {
        let p = dot(vec3<f32>(t[k]) - mean, v);
        pmin = min(pmin, p); pmax = max(pmax, p);
    }
    var e0 = mean + v * pmax;
    var e1 = mean + v * pmin;
    var berr = 0xffffffffu; var bc0 = 0u; var bc1v = 0u; var bidx = 0u;
    for (var ps = 0; ps < 2; ps++) {
        var c0 = to565(e0); var c1 = to565(e1);
        if (c0 < c1) { let s = c0; c0 = c1; c1 = s; }
        let a = rgb565(c0); let bb = rgb565(c1);
        var pal: array<vec3<i32>, 4>;
        if (c0 == c1) { pal[0] = a; pal[1] = a; pal[2] = a; pal[3] = a; }
        else { pal[0] = a; pal[1] = bb; pal[2] = (2 * a + bb) / 3; pal[3] = (a + 2 * bb) / 3; }
        var idx = 0u; var err = 0u;
        var sel: array<u32, 16>;
        for (var k = 0u; k < 16u; k++) {
            var bi = 0u; var be = 0x7fffffff;
            for (var pi = 0u; pi < 4u; pi++) {
                let d = t[k] - pal[pi];
                let dd = d.x * d.x + d.y * d.y + d.z * d.z;
                if (dd < be) { be = dd; bi = pi; }
            }
            sel[k] = bi; err += u32(be); idx |= bi << (2u * k);
        }
        if (ps == 0 || err < berr) { berr = err; bc0 = c0; bc1v = c1; bidx = idx; }
        if (ps == 1 || c0 == c1) { break; }
        var W = array<f32, 4>(1.0, 0.0, 2.0 / 3.0, 1.0 / 3.0);
        var aa = 0.0; var bbs = 0.0; var ab = 0.0;
        var ax = vec3<f32>(0.0); var bxv = vec3<f32>(0.0);
        for (var k = 0u; k < 16u; k++) {
            let wa = W[sel[k]]; let wb = 1.0 - wa;
            aa += wa * wa; bbs += wb * wb; ab += wa * wb;
            ax += wa * vec3<f32>(t[k]); bxv += wb * vec3<f32>(t[k]);
        }
        let det = aa * bbs - ab * ab;
        if (abs(det) < 1e-9) { break; }
        e0 = (bbs * ax - ab * bxv) / det;
        e1 = (aa * bxv - ab * ax) / det;
    }
    outb[2u * g] = bc0 | (bc1v << 16u);
    outb[2u * g + 1u] = bidx;
}
"#;

pub struct Bc1Pipe {
    layout: wgpu::BindGroupLayout,
    pipe: wgpu::ComputePipeline,
}

static BC1: OnceLock<Bc1Pipe> = OnceLock::new();

fn bc1_pipe(gpu: &Gpu) -> &'static Bc1Pipe {
    BC1.get_or_init(|| {
        let d = &gpu.device;
        let module = d.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("bc1"), source: wgpu::ShaderSource::Wgsl(BC1_WGSL.into()),
        });
        let entry = |b: u32, ty: wgpu::BufferBindingType| wgpu::BindGroupLayoutEntry {
            binding: b, visibility: wgpu::ShaderStages::COMPUTE,
            ty: wgpu::BindingType::Buffer { ty, has_dynamic_offset: false, min_binding_size: None }, count: None,
        };
        let layout = d.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[entry(0, wgpu::BufferBindingType::Storage { read_only: true }),
                       entry(1, wgpu::BufferBindingType::Storage { read_only: true }),
                       entry(2, wgpu::BufferBindingType::Storage { read_only: false }),
                       entry(3, wgpu::BufferBindingType::Uniform)],
        });
        let pl = d.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None, bind_group_layouts: &[&layout], push_constant_ranges: &[],
        });
        let pipe = d.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("bc1"), layout: Some(&pl), module: &module, entry_point: Some("bc1"),
            compilation_options: Default::default(), cache: None,
        });
        Bc1Pipe { layout, pipe }
    })
}

/// BC1 blocks of several RGB images at once (each (w, h, rgb bytes)): their blocks' bytes, one Vec per image.
pub fn bc1_encode(gpu: &Gpu, imgs: &[(usize, usize, &[u8])]) -> Result<Vec<Vec<u8>>, String> {
    let d = &gpu.device;
    let mut levels: Vec<[u32; 8]> = Vec::new();
    let mut pix: Vec<u32> = Vec::new();
    let mut nblk = 0u32;
    for &(w, h, rgb) in imgs {
        if rgb.len() != w * h * 3 || w == 0 || h == 0 {
            return Err("bc1_encode: bad image".into());
        }
        let (nbx, nby) = (w.div_ceil(4) as u32, h.div_ceil(4) as u32);
        levels.push([w as u32, h as u32, pix.len() as u32, nbx, nblk, nbx * nby, 0, 0]);
        pix.extend(rgb.chunks_exact(3).map(|c| c[0] as u32 | (c[1] as u32) << 8 | (c[2] as u32) << 16));
        nblk += nbx * nby;
    }
    let p = bc1_pipe(gpu);
    let st = wgpu::BufferUsages::STORAGE;
    let lvb = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("levels"), contents: bytemuck::cast_slice(&levels), usage: st,
    });
    let pixb = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("pix"), contents: bytemuck::cast_slice(&pix), usage: st,
    });
    let nb = (nblk as u64) * 8;
    let outb = d.create_buffer(&wgpu::BufferDescriptor {
        label: Some("blocks"), size: nb, usage: st | wgpu::BufferUsages::COPY_SRC, mapped_at_creation: false,
    });
    let nl = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("n"), contents: bytemuck::cast_slice(&[levels.len() as u32, 0, 0, 0]),
        usage: wgpu::BufferUsages::UNIFORM,
    });
    let bg = d.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None, layout: &p.layout,
        entries: &[wgpu::BindGroupEntry { binding: 0, resource: lvb.as_entire_binding() },
                   wgpu::BindGroupEntry { binding: 1, resource: pixb.as_entire_binding() },
                   wgpu::BindGroupEntry { binding: 2, resource: outb.as_entire_binding() },
                   wgpu::BindGroupEntry { binding: 3, resource: nl.as_entire_binding() }],
    });
    let rb = d.create_buffer(&wgpu::BufferDescriptor {
        label: Some("rb"), size: nb, usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    let mut enc = d.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
    {
        let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor { label: None, timestamp_writes: None });
        pass.set_pipeline(&p.pipe);
        pass.set_bind_group(0, &bg, &[]);
        pass.dispatch_workgroups(nblk.div_ceil(64), 1, 1);
    }
    enc.copy_buffer_to_buffer(&outb, 0, &rb, 0, nb);
    let sub = gpu.queue.submit(Some(enc.finish()));
    let slice = rb.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |r| { let _ = tx.send(r); });
    d.poll(wgpu::PollType::WaitForSubmissionIndex(sub)).map_err(|e| format!("poll: {e:?}"))?;
    rx.recv().map_err(|e| format!("map: {e}"))?.map_err(|e| format!("map: {e:?}"))?;
    let all = slice.get_mapped_range().to_vec();
    rb.unmap();
    Ok(levels.iter().map(|l| all[(l[4] as usize) * 8..((l[4] + l[5]) as usize) * 8].to_vec()).collect())
}
