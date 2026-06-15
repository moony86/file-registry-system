#!/usr/bin/env python3
"""FSYS v2 - Hybrid LAN File Registry Interactive CLI"""
from pathlib import Path
import hashlib
import mimetypes
import os
import requests
import time
import sys
import click
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

console = Console()
MASTER = os.getenv("FSYS_MASTER", "http://localhost:5000")
NODE = os.getenv("FSYS_NODE", "http://localhost:5001")


def sha256_file(path: Path, chunk_size=1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(size):
    size = int(size or 0)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} PB"


# ==========================================
# وظائف النظام الخلفية (Core Logic)
# ==========================================

def fetch_status():
    try:
        r = requests.get(f"{MASTER}/api/status", timeout=5)
        r.raise_for_status()
        data = r.json()
        console.print(Panel(f"[bold]🟢 {data['online_nodes']} nodes online[/bold]", border_style="green"))

        table = Table(title="Connected Storage Nodes")
        table.add_column("Node ID", style="cyan")
        table.add_column("Host:Port")
        table.add_column("Shared Space")
        table.add_column("Used Space")
        table.add_column("Status")

        for node in data.get("nodes", []):
            enabled = "🟢 Yes" if node.get("shared_space_enabled") else "❌ No"
            used = f"{human_size(node.get('shared_space_used_bytes', 0))} / {human_size(node.get('shared_space_limit_bytes', 0))}"
            table.add_row(node["node_id"], f"{node['host']}:{node['port']}", enabled, used, "[green]ONLINE[/green]")
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Cannot connect to master: {exc}[/red]")


def fetch_list():
    try:
        r = requests.get(f"{MASTER}/api/files", timeout=10)
        data = r.json()
        table = Table(title="Registered Files Registry")
        table.add_column("File Name", style="cyan")
        table.add_column("Owner")
        table.add_column("Size")
        table.add_column("Available")
        table.add_column("Shared Space")
        table.add_column("Hits")
        table.add_column("File ID", style="dim")
        for f in data.get("files", []):
            table.add_row(
                f["file_name"],
                f["owner"],
                human_size(f["file_size"]),
                "🟢 yes" if f.get("is_available") else "🔴 no",
                "📦 yes" if f.get("in_shared_space") else "📄 no",
                str(f.get("popularity_score", 0)),
                str(f["file_id"]),
            )
        console.print(table)
        console.print(f"Total: [bold cyan]{data.get('count', 0)}[/bold cyan] files")
    except Exception as exc:
        console.print(f"[red]Error fetching list: {exc}[/red]")


def search_files():
    query = click.prompt("[bold yellow]🔍 Enter search query[/bold yellow]")
    try:
        r = requests.get(f"{MASTER}/api/files/search", params={"q": query}, timeout=10)
        data = r.json()
        table = Table(title=f"Search Results for '{query}'")
        table.add_column("File Name", style="cyan")
        table.add_column("Owner")
        table.add_column("Size")
        table.add_column("Available")
        table.add_column("File ID", style="dim")
        for f in data.get("files", []):
            table.add_row(
                f["file_name"],
                f["owner"],
                human_size(f["file_size"]),
                "yes" if f.get("is_available") else "no",
                str(f["file_id"]),
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error searching files: {exc}[/red]")


def register_local():
    path = click.prompt("[bold yellow]📁 Enter local file path to register[/bold yellow]")
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    owner = click.prompt("👤 Enter owner name", default="user")
    node_url = click.prompt("🌐 Storage node URL", default=NODE)

    console.print(f"Hashing [bold cyan]{file_path.name}[/bold cyan]...")
    content_hash = sha256_file(file_path)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    try:
        r = requests.post(f"{node_url}/api/files/register", json={
            "file_name": file_path.name,
            "owner": owner,
            "physical_path": str(file_path),
            "content_hash": content_hash,
            "mime_type": mime_type,
        }, timeout=30)
        data = r.json()
        if r.status_code == 201:
            console.print("[green]✔ Registered metadata/local location successfully![/green]")
            console.print(f"File ID: [cyan]{data['file_id']}[/cyan]")
        else:
            console.print(f"[red]Failed: {data}[/red]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


def cache_file():
    path = click.prompt("[bold yellow]📦 Enter file path to upload into Shared Space[/bold yellow]")
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    owner = click.prompt("👤 Enter owner name", default="user")
    node_url = click.prompt("🌐 Target node URL", default=NODE)
    is_pinned = click.confirm("📌 Mark this file as PINNED (Permanent)?", default=False)

    location_type = "PINNED" if is_pinned else "CACHED"
    try:
        with file_path.open("rb") as fh:
            r = requests.post(
                f"{node_url}/api/files/cache",
                files={"file": (file_path.name, fh)},
                data={"owner": owner, "location_type": location_type},
                timeout=300,
            )
        data = r.json()
        if r.status_code == 201:
            console.print(f"[green]✔ Cached in Shared Space ({location_type})[/green]")
            console.print(f"File ID: [cyan]{data['file_id']}[/cyan]")
            console.print(f"Deduped on node: [yellow]{data.get('deduped_on_node')}[/yellow]")
        else:
            console.print(f"[red]Failed: {data}[/red]")
    except Exception as exc:
        console.print(f"[red]Error during caching: {exc}[/red]")


def download_file():
    file_id = click.prompt("[bold yellow]📥 Enter File ID to download[/bold yellow]")
    output = click.prompt("📂 Target output directory", default=".")

    try:
        r = requests.get(f"{MASTER}/api/files/{file_id}/location", timeout=10)
        if r.status_code != 200:
            console.print("[red]File not found in registry[/red]")
            return
        file_info = r.json()
        node_url = f"http://{file_info['node']['host']}:{file_info['node']['port']}"
        output_path = Path(output).expanduser().resolve() / file_info["file_name"]
        output_path.parent.mkdir(parents=True, exist_ok=True)

        console.print(f"Fetching from {node_url} [{file_info['location_type']}]...")
        with requests.get(f"{node_url}/api/files/{file_id}/download", stream=True, timeout=300) as response:
            if response.status_code != 200:
                console.print(f"[red]Download failed: HTTP {response.status_code}[/red]")
                return
            with output_path.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)

        actual_hash = sha256_file(output_path)
        if actual_hash != file_info["content_hash"]:
            output_path.unlink(missing_ok=True)
            console.print("[red]Checksum mismatch after download; file deleted for safety[/red]")
            return
        console.print(f"[green]✔ Downloaded successfully to:[/green] {output_path}")
    except Exception as exc:
        console.print(f"[red]Error downloading file: {exc}[/red]")


def watch_nodes():
    def render():
        try:
            r = requests.get(f"{MASTER}/api/status", timeout=5)
            data = r.json()
            table = Table()
            table.add_column("Node ID", style="cyan")
            table.add_column("Shared Used Space")
            table.add_column("Status")
            for node in data.get("nodes", []):
                used = f"{human_size(node.get('shared_space_used_bytes', 0))} / {human_size(node.get('shared_space_limit_bytes', 0))}"
                table.add_row(node["node_id"], used, "[green]● LIVE[/green]")
            return Panel(table, title=f"FSYS Live Monitor ({data.get('online_nodes', 0)} Nodes)", border_style="magenta")
        except Exception:
            return Panel("[red]Connection lost to Master Server...[/red]")

    console.print("[yellow]Press Ctrl+C to return to main menu[/yellow]")
    try:
        with Live(render(), refresh_per_second=0.5) as live:
            while True:
                time.sleep(2)
                live.update(render())
    except KeyboardInterrupt:
        pass


# ==========================================
# القائمة التفاعلية الرئيسية (Main Menu Loop)
# ==========================================

@click.command()
def main():
    """FSYS v2 - Interactive Shell Gateway"""
    while True:
        console.print("\n" + "="*45, style="magenta")
        console.print("📁 [bold white]FSYS v2: LAN Hybrid File Registry[/bold white]")
        console.print("="*45, style="magenta")
        console.print("[1] 🟢 View Cluster Status")
        console.print("[2] 📋 List All Registered Files")
        console.print("[3] 🔍 Search Registry")
        console.print("[4] 📄 Register Local File (Metadata Only)")
        console.print("[5] 📦 Upload/Cache File to Shared Space")
        console.print("[6] 📥 Download File by ID")
        console.print("[7] 📺 Live Cluster Monitor (Watch)")
        console.print("[8] ❌ Exit")
        console.print("="*45, style="magenta")

        choice = click.prompt("👉 Select an option", type=click.Choice(['1', '2', '3', '4', '5', '6', '7', '8']))

        if choice == '1':
            fetch_status()
        elif choice == '2':
            fetch_list()
        elif choice == '3':
            search_files()
        elif choice == '4':
            register_local()
        elif choice == '5':
            cache_file()
        elif choice == '6':
            download_file()
        elif choice == '7':
            watch_nodes()
        elif choice == '8':
            console.print("[bold yellow]Goodbye![/bold yellow]")
            sys.exit(0)

        time.sleep(1)


if __name__ == "__main__":
    main()
