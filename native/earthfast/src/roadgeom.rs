//! Road geometry helpers off the worker processes' Python loops (2026-10-23: a Steam Deck's road, block and far
//! building processes each spent 14-21 CPU-s of a teleport in roads._dedupe alone).

use numpy::{IntoPyArray, PyArray1, PyReadonlyArray2};
use pyo3::prelude::*;

/// roads._dedupe: the indices of a polyline's points kept when every point closer than tol to the previous kept one
/// is dropped (the first and the last kept; a last kept point within tol of the end is replaced by the end).
#[pyfunction]
pub fn dedupe_polyline<'py>(py: Python<'py>, xy: PyReadonlyArray2<'py, f64>, tol: f64) -> Bound<'py, PyArray1<i64>> {
    let a = xy.as_array();
    let n = a.shape()[0];
    if n < 3 {
        return (0..n as i64).collect::<Vec<_>>().into_pyarray(py);
    }
    let d = |i: usize, j: usize| -> f64 { (a[[i, 0]] - a[[j, 0]]).hypot(a[[i, 1]] - a[[j, 1]]) };
    let mut keep: Vec<usize> = vec![0];
    for k in 1..n - 1 {
        if d(k, *keep.last().unwrap()) >= tol {
            keep.push(k);
        }
    }
    if d(n - 1, *keep.last().unwrap()) < tol && keep.len() > 1 {
        *keep.last_mut().unwrap() = n - 1;
    } else {
        keep.push(n - 1);
    }
    keep.into_iter().map(|k| k as i64).collect::<Vec<_>>().into_pyarray(py)
}
