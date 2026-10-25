#!/usr/bin/env python3
"""Build PyInstaller's Windows bootloader (run.exe, the one-file console variant) from its source, for
tools/build_app.py: build/bootloader/<PyInstaller version>/run.exe, used instead of the prebuilt one in the wheel.

Why (2026-10-17): VirusTotal flagged the 1.4.35 .exe (2/60: Bkav Pro and SecureAge, generic "malicious"). Every
PyInstaller app built from the wheel starts with the same prebuilt run.exe, malware's included, so heuristic engines
learn its bytes; a bootloader compiled here differs from it and drops that match. PyInstaller's own advice for these
false positives (https://pyinstaller.org/en/stable/bootloader-building.html).

    python3 tools/build_bootloader.py --pyinstaller 6.22.3     # Linux: cross build (mingw-w64 gcc, or zig cc)
    python tools/build_bootloader.py                           # Windows: MSVC (Visual Studio Build Tools), as CI

The version must be the PyInstaller that build_app.py runs (bootloader and archive format go together; build_app.py
takes only the one built for its own version). It defaults to the PyInstaller in this Python. The source is the
sdist from PyPI (pip download). On Linux the compiler is --cc, else x86_64-w64-mingw32-gcc, else zig (on PATH or the
ziglang pip package in --zig-python) as `zig cc -target x86_64-windows-gnu` behind a wrapper that drops the GNU ld
flags lld does not take. That build links the Universal CRT (api-ms-win-crt-*, part of Windows 10+; the Python
inside needs it anyway); the prebuilt one imports only kernel32/user32/advapi32.

One change to the source (TEMPNAM below): the one-file .exe unpacks into %TEMP%\\_MEI<pid><suffix> named by the C
runtime's _wtempnam, and Wine's Universal CRT (Proton: players run the .exe in the game's prefix) keeps only 3
characters of the prefix ("_ME36FC.tmp", GetTempFileName's rule); the unpacked child then stops with "Security
validation failure: unexpected name of application's home directory!" (seen 2026-10-17 under Wine 11.18 with the zig
build; the prebuilt and MSVC builds carry their own static _wtempnam). The bootloader names it itself, as Windows'
_wtempnam does: the temp folder, the prefix, a hex suffix (CreateDirectoryW fails on a name in use; 5 tries).
"""
import argparse
import glob
import os
import shutil
import stat
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "bootloader")
IS_WIN = os.name == "nt"


TEMPNAM_CALL = "_wtempnam(tempdir_path, prefix);"
TEMPNAM_DEF = "int\npyi_create_temporary_application_directory(struct PYI_CONTEXT *pyi_ctx)\n"
TEMPNAM = r"""/* BeamNG.Earth (tools/build_bootloader.py): _wtempnam's name without the C runtime's _wtempnam (Wine's keeps
 * 3 characters of the prefix). dir + prefix + a hex suffix; the caller frees it. */
static wchar_t *
bnge_tempnam(const wchar_t *dir, const wchar_t *prefix, int attempt)
{
    size_t dir_len = wcslen(dir);
    size_t len = dir_len + wcslen(prefix) + 16;
    const wchar_t *sep = (dir_len > 0 && dir[dir_len - 1] != L'\\' && dir[dir_len - 1] != L'/') ? L"\\" : L"";
    unsigned int suffix = ((unsigned int)GetTickCount() * 2654435761u + (unsigned int)attempt * 40503u) & 0xffffff;
    wchar_t *path = (wchar_t *)malloc(len * sizeof(wchar_t));
    if (path == NULL) {
        return NULL;
    }
    _snwprintf(path, len, L"%ls%ls%ls%x", dir, sep, prefix, suffix);
    path[len - 1] = 0;
    return path;
}

"""


def patch_tempnam(boot):
    """pyi_utils_win32.c: the temp folder named by bnge_tempnam (see the docstring). Fails loudly when a PyInstaller
    release changed the code it replaces."""
    p = os.path.join(boot, "src", "pyi_utils_win32.c")
    with open(p, encoding="utf-8") as f:
        c = f.read()
    if "bnge_tempnam" in c:
        return
    if c.count(TEMPNAM_CALL) != 1 or c.count(TEMPNAM_DEF) != 1:
        sys.exit(f"{p}: the _wtempnam call to replace is not there (another PyInstaller?): update TEMPNAM")
    c = c.replace(TEMPNAM_CALL, "bnge_tempnam(tempdir_path, prefix, i);").replace(TEMPNAM_DEF, TEMPNAM + TEMPNAM_DEF)
    with open(p, "w", encoding="utf-8") as f:
        f.write(c)


def installed_version():
    try:
        import PyInstaller
        return PyInstaller.__version__
    except ImportError:
        return None


def source(ver, work):
    """The sdist's bootloader folder (downloaded once per version)."""
    src = os.path.join(work, f"pyinstaller-{ver}")
    if not os.path.isdir(os.path.join(src, "bootloader")):
        subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--no-binary", ":all:",
                        f"pyinstaller=={ver}", "-d", work], check=True)
        tgz = os.path.join(work, f"pyinstaller-{ver}.tar.gz")
        with tarfile.open(tgz) as t:
            t.extractall(work, filter="data")
    return os.path.join(src, "bootloader")


def zig_wrapper(work, zig):
    """A mingw-like cc: zig cc for x86_64-windows-gnu. waf adds GNU ld flags (lld: 'unsupported linker arg') and
    -D_WIN32_WINNT=0x0601 over zig's own 0x0a00 (-Werror: 'macro redefined'; the later, PyInstaller's, wins)."""
    path = os.path.join(work, "zcc")
    with open(path, "w") as f:
        f.write("#!/bin/sh\n"
                "for a; do shift; case \"$a\" in -Wl,--enable-auto-import|-Wl,-Bstatic|-Wl,-Bdynamic) ;; "
                "*) set -- \"$@\" \"$a\";; esac; done\n"
                f"exec {zig} cc -target x86_64-windows-gnu -Wno-macro-redefined \"$@\"\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def cross_cc(a, work):
    if a.cc:
        return a.cc
    gcc = shutil.which("x86_64-w64-mingw32-gcc")
    if gcc:
        return gcc
    if shutil.which("zig"):
        return zig_wrapper(work, shutil.which("zig"))
    py = a.zig_python or sys.executable
    if subprocess.run([py, "-c", "import ziglang"], capture_output=True).returncode == 0:
        return zig_wrapper(work, f"'{py}' -m ziglang")
    sys.exit("no Windows C compiler: install mingw-w64 gcc or zig (pip install ziglang), or pass --cc")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pyinstaller", default=installed_version(),
                    help="the PyInstaller version build_app.py runs (default: this Python's)")
    ap.add_argument("--cc", help="Linux: the Windows C compiler (default: mingw-w64 gcc, else zig)")
    ap.add_argument("--zig-python", help="Linux: a Python with the ziglang package (default: this one)")
    a = ap.parse_args()
    if not a.pyinstaller:
        sys.exit("PyInstaller is not installed in this Python: pass --pyinstaller VERSION")
    work = os.path.join(OUT, "src")
    os.makedirs(work, exist_ok=True)
    boot = source(a.pyinstaller, work)
    patch_tempnam(boot)
    env = dict(os.environ)
    if not IS_WIN:
        env["CC"] = cross_cc(a, work)
    shutil.rmtree(os.path.join(boot, "build"), ignore_errors=True)   # a configure for another compiler
    waf = [sys.executable, "./waf"]
    subprocess.run(waf + ["configure", "--target-arch=64bit"], check=True, cwd=boot, env=env)
    subprocess.run(waf + ["build_release"], check=True, cwd=boot, env=env)
    built = glob.glob(os.path.join(boot, "build", "release", "run.exe"))
    if not built:
        sys.exit("waf finished without build/release/run.exe")
    dst = os.path.join(OUT, a.pyinstaller)
    os.makedirs(dst, exist_ok=True)
    shutil.copyfile(built[0], os.path.join(dst, "run.exe"))
    print(f"built {os.path.join(dst, 'run.exe')} ({os.path.getsize(built[0]) // 1024} KB)")


if __name__ == "__main__":
    main()
