#!/usr/bin/env python3
"""FSYS v2 - Hybrid LAN File Registry CLI (Architecture Validation Mode)"""
from pathlib import Path
import hashlib
import mimetypes
import os
import requests
import time
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


@click.group()
def cli():
    """FSYS v2 - Registry + Shared Space (Testing Dashboard)"""
    pass


@cli.command()
def status():
    try:
        r = requests.get(f"{MASTER}/api/status", timeout=5)
        r.raise_for_status()
        data = r.json()
        console.print(Panel(f"[bold]🟢 {data['online_nodes']} nodes online[/bold]", border_style="green"))

        table = Table()
        table.add_column("Node ID", style="cyan")
        table.add_column("Host:Port")
        table.add_column("Shared Space")
        table.add_column("Used")
        table.add_column("Status")

        for node in data.get("nodes", []):
            enabled = "yes" if node.get("shared_space_enabled") else "no"
            used = f"{human_size(node.get('shared_space_used_bytes', 0))} / {human_size(node.get('shared_space_limit_bytes', 0))}"
            table.add_row(
                node["node_id"],
                f"{node['host']}:{node['port']}",
                enabled,
                used,
                "[green]ONLINE[/green]",
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Cannot connect to master: {exc}[/red]")


@cli.command()
@click.argument("path")
@click.option("--node", default=NODE, help="Storage/source node URL")
@click.option("--owner", default="user", help="File owner")
def register(path, node, owner):
    """Register local file metadata only; no copy into Shared Space."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    console.print(f"Hashing [bold]{file_path.name}[/bold]...")
    content_hash = sha256_file(file_path)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    try:
        r = requests.post(f"{node}/api/files/register", json={
            "file_name": file_path.name,
            "owner": owner,
            "physical_path": str(file_path),
            "content_hash": content_hash,
            "mime_type": mime_type,
        }, timeout=30)
        data = r.json()
        if r.status_code == 201:
            console.print("[green]Registered metadata/local location[/green]")
            console.print(f"File ID: [cyan]{data['file_id']}[/cyan]")
            console.print(f"Content Hash: [dim]{data['content_hash']}[/dim]")
        else:
            console.print(f"[red]Failed: {data}[/red]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@cli.command("cache")
@click.argument("path")
@click.option("--node", default=NODE, help="Storage node URL")
@click.option("--owner", default="user", help="File owner")
@click.option("--pinned", is_flag=True, help="Mark as PINNED instead of CACHED")
def cache_file(path, node, owner, pinned):
    """Upload file into managed Shared Space, with node-side dedupe."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    location_type = "PINNED" if pinned else "CACHED"
    try:
        with file_path.open("rb") as fh:
            r = requests.post(
                f"{node}/api/files/cache",
                files={"file": (file_path.name, fh)},
                data={"owner": owner, "location_type": location_type},
                timeout=300,
            )
        data = r.json()
        if r.status_code == 201:
            console.print(f"[green]Cached in Shared Space[/green] ({location_type})")
            console.print(f"File ID: [cyan]{data['file_id']}[/cyan]")
            console.print(f"Deduped on node: {data.get('deduped_on_node')}")
            console.print(f"Path: [dim]{data.get('shared_space_path')}[/dim]")
        else:
            console.print(f"[red]Failed: {data}[/red]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@cli.command()
@click.argument("file_id")
def locate(file_id):
    try:
        r = requests.get(f"{MASTER}/api/files/{file_id}/location", timeout=10)
        data = r.json()
        if r.status_code == 200:
            console.print("[green]Found[/green]")
            console.print(f"File: {data['file_name']} ({human_size(data['file_size'])})")
            console.print(f"Hash: [dim]{data['content_hash']}[/dim]")
            console.print(f"Location Type: [bold]{data['location_type']}[/bold]")
            console.print(f"Node: {data['node']['host']}:{data['node']['port']}")
            console.print(f"Path: [dim]{data['physical_path']}[/dim]")
        else:
            console.print(f"[red]{data.get('error', 'Not found')}[/red]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@cli.command(name="list")
def list_files():
    try:
        r = requests.get(f"{MASTER}/api/files", timeout=10)
        data = r.json()
        table = Table()
        table.add_column("File Name", style="cyan")
        table.add_column("Owner")
        table.add_column("Size")
        table.add_column("Available")
        table.add_column("Shared")
        table.add_column("Hits")
        table.add_column("File ID", style="dim")
        for f in data.get("files", []):
            # تمييز الملفات الـ HOT بصرياً داخل الـ CLI للاختبار الواضح
            is_hot = f.get("is_hot", 0) == 1
            name_display = f"[bold red]🔥 {f['file_name']}[/bold red]" if is_hot else f["file_name"]

            table.add_row(
                name_display,
                f["owner"],
                human_size(f["file_size"]),
                "yes" if f.get("is_available") else "no",
                "yes" if f.get("in_shared_space") else "no",
                str(f.get("popularity_score", 0)),
                str(f["file_id"])[:8] + "...",
            )
        console.print(table)
        console.print(f"Total: {data.get('count', 0)} files")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@cli.command()
@click.argument("query")
def search(query):
    try:
        r = requests.get(f"{MASTER}/api/files/search", params={"q": query}, timeout=10)
        data = r.json()
        table = Table()
        table.add_column("File Name", style="cyan")
        table.add_column("Owner")
        table.add_column("Size")
        table.add_column("Available")
        table.add_column("Shared")
        table.add_column("Hits")
        table.add_column("File ID", style="dim")
        for f in data.get("files", []):
            is_hot = f.get("is_hot", 0) == 1
            name_display = f"[bold red]🔥 {f['file_name']}[/bold red]" if is_hot else f["file_name"]

            table.add_row(
                name_display,
                f["owner"],
                human_size(f["file_size"]),
                "yes" if f.get("is_available") else "no",
                "yes" if f.get("in_shared_space") else "no",
                str(f.get("popularity_score", 0)),
                str(f["file_id"])[:8] + "...",
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@cli.command()
@click.argument("file_id")
@click.option("--unpin", is_flag=True, help="إلغاء وسم الـ HOT وإرجاع الملف لوضعه الطبيعي")
def pin(file_id, unpin):
    """[الأدمن] وسم ملف كـ HOT 🔥 (Pinned Content) لمنحه أولوية قصوى ومنع حذفه."""
    is_hot_value = 0 if unpin else 1
    token = os.getenv("FSYS_NODE_TOKEN", "dev-token")
    headers = {"X-FSYS-Token": token}

    try:
        r = requests.post(
            f"{MASTER}/api/files/{file_id}/hot",
            json={"is_hot": is_hot_value},
            headers=headers,
            timeout=5
        )
        if r.status_code == 200:
            if unpin:
                console.print(f"[green]✓[/green] تم إلغاء تثبيت الملف [yellow]{file_id}[/yellow] بنجاح.")
            else:
                console.print(f"[bold red]🔥 تم تثبيت ووسم الملف كـ HOT بنجاح! ({file_id})[/bold red]")
        else:
            error_msg = r.json().get("error", "Unknown error")
            console.print(f"[red]❌ فشل الإجراء: {error_msg} (HTTP {r.status_code})[/red]")
    except Exception as exc:
        console.print(f"[red]❌ فشل الاتصال بالسيرفر الماستر: {exc}[/red]")


@cli.command()
@click.argument("file_id")
@click.option("--output", "-o", default=".", help="Output directory")
def download(file_id, output):
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
                try:
                    console.print(f"[red]Download failed: {response.json()}[/red]")
                except Exception:
                    console.print(f"[red]Download failed: HTTP {response.status_code}[/red]")
                return
            with output_path.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)

        actual_hash = sha256_file(output_path)
        if actual_hash != file_info["content_hash"]:
            output_path.unlink(missing_ok=True)
            console.print("[red]Checksum mismatch after download; file deleted[/red]")
            return
        console.print(f"[green]Downloaded:[/green] {output_path}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@cli.command()
def watch():
    def render():
        try:
            r = requests.get(f"{MASTER}/api/status", timeout=5)
            data = r.json()
            table = Table()
            table.add_column("Node")
            table.add_column("Shared Used")
            table.add_column("Status")
            for node in data.get("nodes", []):
                used = f"{human_size(node.get('shared_space_used_bytes', 0))} / {human_size(node.get('shared_space_limit_bytes', 0))}"
                table.add_row(node["node_id"], used, "[green]LIVE[/green]")
            return Panel(table, title=f"Nodes ({data.get('online_nodes', 0)} online)")
        except Exception:
            return Panel("[red]Connection lost[/red]")

    with Live(render(), refresh_per_second=0.5) as live:
        while True:
            time.sleep(3)
            live.update(render())


if __name__ == "__main__":
    cli()
