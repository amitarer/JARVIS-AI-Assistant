"""Install approved portable tools inside this project; never modify global state.

Only official HTTPS archives are downloaded. Their checksums are verified before
safe ZIP extraction. npm lifecycle scripts are disabled in the initial install.
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import urllib.request
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".devtools"


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-local-setup", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def download(url, target):
    if not url.startswith("https://"):
        raise ValueError("HTTPS required")
    temporary = target.with_suffix(target.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-local-setup"})
    with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    temporary.replace(target)


def extract_checked(archive, destination, *, strip_prefix=""):
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with ZipFile(archive) as source:
        for item in source.infolist():
            name = item.filename
            if strip_prefix:
                if not name.startswith(strip_prefix):
                    raise ValueError("Unexpected ZIP root")
                name = name[len(strip_prefix):]
            if not name:
                continue
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
                raise ValueError("Unsafe ZIP path")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("ZIP symlinks not permitted")
            target = destination.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError("ZIP extraction escaped installation root")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as reader, target.open("wb") as writer:
                    shutil.copyfileobj(reader, writer)


def install_portable(name, url, checksum, filename, strip_prefix=""):
    archive = TOOLS / "downloads" / filename
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
        download(url, archive)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != checksum:
        raise ValueError(f"Checksum mismatch for {name}")
    target = TOOLS / name
    marker = target / ".archive-sha256"
    if not marker.is_file() or marker.read_text().strip() != checksum:
        extract_checked(archive, target, strip_prefix=strip_prefix)
        marker.write_text(checksum, encoding="ascii")
    print(f"Verified portable {name}: {filename}", flush=True)
    return {"archive": filename, "url": url, "sha256": actual, "directory": str(target)}


def local_environment():
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(TOOLS / "node"), str(TOOLS / "git/cmd"), env.get("PATH", "")))
    # npm must not inherit user registry credentials or write its cache globally.
    empty_npm = TOOLS / "empty.npmrc"
    global_npm = TOOLS / "empty-global.npmrc"
    empty_git = TOOLS / "empty.gitconfig"
    empty_npm.touch(exist_ok=True)
    global_npm.touch(exist_ok=True)
    empty_git.touch(exist_ok=True)
    for key in list(env):
        if key.upper().startswith("NPM_CONFIG_") or key.upper() in {"NPM_TOKEN", "NODE_AUTH_TOKEN"}:
            env.pop(key)
    env.update(NPM_CONFIG_USERCONFIG=str(empty_npm), NPM_CONFIG_GLOBALCONFIG=str(global_npm),
               NPM_CONFIG_CACHE=str(TOOLS / "npm-cache"), NPM_CONFIG_AUDIT="false",
               NPM_CONFIG_FUND="false", NPM_CONFIG_UPDATE_NOTIFIER="false",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(empty_git))
    return env


def main():
    if os.name != "nt":
        raise RuntimeError("This approved setup targets native Windows x64")
    (TOOLS / "downloads").mkdir(parents=True, exist_ok=True)
    pinned = ROOT / "development/locks/portable-tools.json"
    if not pinned.is_file():
        raise RuntimeError("Pinned portable-tool manifest required; no automatic updates")
    records = get_pinned_tools(pinned)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(install_portable, name, row["url"], row["sha256"], row["archive"],
                   row["archive"].removesuffix(".zip") + "/" if name == "node" else "")
                   for name, row in records.items()}
        manifest = {name: future.result() for name, future in futures.items()}
    env = local_environment()
    for executable, arguments in [(TOOLS / "node/node.exe", ["--version"]),
                                  (TOOLS / "git/cmd/git.exe", ["--version"])]:
        result = subprocess.run([str(executable), *arguments], env=env, capture_output=True, text=True,
                                timeout=20, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        print(result.stdout.strip(), flush=True)
    (TOOLS / "installation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


def get_pinned_tools(path):
    """Validate committed versions without querying or selecting newer releases."""
    records = json.loads(path.read_text(encoding="utf-8"))
    if set(records) != {"node", "git"}:
        raise ValueError("Unexpected portable tool inventory")
    for name, row in records.items():
        prefix = "https://nodejs.org/dist/" if name == "node" else "https://github.com/git-for-windows/git/releases/download/"
        if not row["url"].startswith(prefix) or len(row["sha256"]) != 64:
            raise ValueError("Invalid official archive or SHA-256")
        if Path(row["archive"]).name != row["archive"] or not row["url"].endswith("/" + row["archive"]):
            raise ValueError("Invalid portable archive name")
    return records


def discover_releases_for_review():
    """Read-only helper; newly discovered releases are never installed by startup."""
    node_release = next(row for row in get_json("https://nodejs.org/dist/index.json")
                        if row["version"].startswith("v24.") and row.get("lts"))
    node_version = node_release["version"]
    node_filename = f"node-{node_version}-win-x64.zip"
    node_base = f"https://nodejs.org/dist/{node_version}/"
    with urllib.request.urlopen(node_base + "SHASUMS256.txt", timeout=30) as response:
        checksums = response.read().decode("utf-8")
    node_checksum = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == node_filename)
    git_release = get_json("https://api.github.com/repos/git-for-windows/git/releases/latest")
    git_asset = next(asset for asset in git_release["assets"]
                     if asset["name"].startswith("MinGit-") and asset["name"].endswith("-64-bit.zip")
                     and "busybox" not in asset["name"])
    digest = git_asset.get("digest", "")
    if not digest.startswith("sha256:"):
        raise RuntimeError("Official GitHub release has no SHA-256 digest; do not install unchecked")
    return {"node": {"archive": node_filename, "url": node_base + node_filename, "sha256": node_checksum},
            "git": {"archive": git_asset["name"], "url": git_asset["browser_download_url"], "sha256": digest.split(":", 1)[1]}}


if __name__ == "__main__":
    raise SystemExit(main())
