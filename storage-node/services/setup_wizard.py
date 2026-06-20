from pathlib import Path
import os
import shutil
import sys

import requests


PLACEHOLDER_MASTER_VALUES = {
    "",
    "localhost",
    "http://localhost:5000",
    "https://localhost:5000",
}


def runtime_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def env_path():
    return runtime_dir() / ".env"


def read_env_values(path):
    values = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def is_first_run_config(path=None):
    path = path or env_path()
    if not path.exists():
        return True
    values = read_env_values(path)
    master_urls = values.get("MASTER_URLS") or values.get("MASTER_URL") or ""
    normalized = master_urls.strip().lower()
    return normalized in PLACEHOLDER_MASTER_VALUES


def parse_size_bytes(value):
    text = (value or "").strip().replace(" ", "").upper()
    if not text:
        raise ValueError("Storage size is required")
    if text.endswith("GB"):
        number = float(text[:-2])
        multiplier = 1024 ** 3
    elif text.endswith("TB"):
        number = float(text[:-2])
        multiplier = 1024 ** 4
    else:
        number = float(text)
        multiplier = 1024 ** 3
    size = int(number * multiplier)
    if size <= 1024 ** 3:
        raise ValueError("Storage size must be greater than 1GB")
    return size


def prompt_with_default(label, default):
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def prompt_master_urls():
    while True:
        value = prompt_with_default("Master URL(s), comma separated", "http://192.168.1.14:5000")
        urls = [url.strip().rstrip("/") for url in value.split(",") if url.strip()]
        if urls and all(url.startswith(("http://", "https://")) for url in urls):
            return ",".join(urls)
        print("Master URL must start with http:// or https://")


def prompt_port():
    while True:
        value = prompt_with_default("Node Port", "5001")
        try:
            port = int(value)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
        print("Port must be a number from 1 to 65535")


def prompt_shared_space_dir():
    while True:
        value = prompt_with_default("Shared Space Directory", "./shared_space")
        path = Path(value).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            return value
        except Exception as exc:
            print(f"Could not create shared space directory: {exc}")


def prompt_storage_size():
    while True:
        value = prompt_with_default("Storage Size (GB/TB)", "20GB")
        try:
            return parse_size_bytes(value)
        except ValueError as exc:
            print(str(exc))


def prompt_local_libraries():
    print("Local Libraries, one path per line. Leave blank and press Enter to finish.")
    libraries = []
    while True:
        value = input("Library path: ").strip()
        if not value:
            break
        path = Path(value).expanduser()
        if not path.exists():
            print(f"Warning: library does not exist and will be skipped: {value}")
            continue
        if not path.is_dir():
            print(f"Warning: library is not a directory and will be skipped: {value}")
            continue
        libraries.append(value)
    return ",".join(libraries)


def prompt_token():
    return prompt_with_default("Node Token", "dev-token")


def write_env_file(path, values):
    if path.exists():
        shutil.copyfile(path, path.with_name(".env.backup"))

    lines = [
        "NODE_ID=auto",
        "NODE_HOST=auto",
        f"NODE_PORT={values['node_port']}",
        "",
        f"MASTER_URLS={values['master_urls']}",
        f"FSYS_NODE_TOKEN={values['node_token']}",
        "",
        "SHARED_SPACE_ENABLED=true",
        f"SHARED_SPACE_DIR={values['shared_space_dir']}",
        f"SHARED_SPACE_LIMIT_BYTES={values['shared_space_limit_bytes']}",
        "",
        "THUMBNAILS_DIR=./thumbnails",
        "DATA_DIR=./data",
        "",
        f"LOCAL_LIBRARY_DIRS={values['local_library_dirs']}",
        "",
        f"FSYS_CORS_ORIGINS={values['master_urls']},http://localhost:5000,http://127.0.0.1:5000",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def default_local_libraries():
    home = Path.home()
    candidates = [home / "Videos", home / "Downloads"]
    return ",".join(str(path) for path in candidates if path.exists() and path.is_dir())


def create_default_env(path=None):
    path = path or env_path()
    values = {
        "master_urls": "http://localhost:5000",
        "node_port": 5001,
        "shared_space_dir": "./shared_space",
        "shared_space_limit_bytes": 20 * 1024 ** 3,
        "local_library_dirs": default_local_libraries(),
        "node_token": "dev-token",
    }
    Path(values["shared_space_dir"]).mkdir(parents=True, exist_ok=True)
    write_env_file(path, values)
    print(f"Created default configuration: {path}")
    print("Node will start with localhost master fallback. Use --setup or the Control UI to reconfigure.")
    return values


def test_master(master_urls):
    first_url = master_urls.split(",", 1)[0].rstrip("/")
    try:
        response = requests.get(f"{first_url}/api/status", timeout=3)
        if response.ok:
            print("OK: Master reachable")
            return True
    except Exception:
        pass
    print("WARNING: Master not reachable. Node can still start and retry in background.")
    return False


def run_setup_wizard(path=None):
    path = path or env_path()
    print("")
    print("## FSYS Node First Run Setup")
    print("")

    values = {
        "master_urls": prompt_master_urls(),
        "node_port": prompt_port(),
        "shared_space_dir": prompt_shared_space_dir(),
        "shared_space_limit_bytes": prompt_storage_size(),
        "local_library_dirs": prompt_local_libraries(),
        "node_token": prompt_token(),
    }

    print("")
    print("Configuration summary:")
    print(f"MASTER_URLS={values['master_urls']}")
    print(f"PORT={values['node_port']}")
    print(f"SPACE={values['shared_space_dir']}")
    print(f"SIZE={values['shared_space_limit_bytes']}")
    print(f"LIBRARIES={values['local_library_dirs'] or '(none)'}")
    print("")

    confirm = input("Save configuration? Y/N [Y]: ").strip().lower() or "y"
    if confirm not in {"y", "yes"}:
        print("Setup cancelled. Configuration was not changed.")
        return False

    write_env_file(path, values)
    print(f"Saved configuration: {path}")
    test_master(values["master_urls"])
    return True


def reset_config(path=None):
    path = path or env_path()
    if path.exists():
        old_path = path.with_name(".env.old")
        if old_path.exists():
            old_path.unlink()
        path.rename(old_path)
        print(f"Moved existing .env to {old_path}")
    return run_setup_wizard(path)


def maybe_run_setup_wizard(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    path = env_path()
    if "--reset-config" in argv:
        reset_config(path)
        return
    if "--setup" in argv:
        run_setup_wizard(path)
        return
    if not path.exists():
        create_default_env(path)
        return
    if is_first_run_config(path):
        run_setup_wizard(path)
