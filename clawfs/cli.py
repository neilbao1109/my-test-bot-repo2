"""ClawFS CLI."""
from __future__ import annotations

import os
import sys

import click

from .core import ClawFS


def _fs(ctx) -> ClawFS:
    return ClawFS.local(ctx.obj["root"])


@click.group()
@click.option("--root", default=lambda: os.environ.get("CLAWFS_ROOT", "./clawfs-data"))
@click.pass_context
def cli(ctx, root):
    ctx.ensure_object(dict)
    ctx.obj["root"] = root


@cli.command()
@click.argument("path")
@click.argument("file", type=click.File("rb"))
@click.pass_context
def write(ctx, path, file):
    """Write FILE content to ref PATH."""
    h, created = _fs(ctx).put_ref(path, file.read())
    click.echo(f"{path} -> {h} ({'new' if created else 'updated'})")


@cli.command()
@click.argument("path")
@click.pass_context
def read(ctx, path):
    """Read ref PATH to stdout."""
    data = _fs(ctx).resolve_ref(path)
    if data is None:
        click.echo(f"not found: {path}", err=True)
        sys.exit(1)
    sys.stdout.buffer.write(data)


@cli.command()
@click.option("--prefix", default="")
@click.pass_context
def ls(ctx, prefix):
    for r in _fs(ctx).list_refs(prefix):
        click.echo(f"{r.hash[:12]}  {r.path}")


@cli.command()
@click.argument("path")
@click.pass_context
def rm(ctx, path):
    if _fs(ctx).delete_ref(path):
        click.echo(f"deleted {path}")
    else:
        click.echo(f"not found: {path}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("path")
@click.option("--ttl", type=int, default=None, help="seconds")
@click.pass_context
def share(ctx, path, ttl):
    token = _fs(ctx).create_share(path, ttl)
    click.echo(token)


@cli.command()
@click.pass_context
def gc(ctx):
    n = _fs(ctx).gc()
    click.echo(f"removed {n} blobs")


@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.pass_context
def admin(ctx):
    """Operator CLI: tenant create/list/rotate-token/set-quota/delete, usage.

    Use `clawfs admin --help` for the full subcommand list.
    """
    from .admin import main as admin_main
    # rebuild argv: prepend --root from the click context so admin sees it
    extra = list(ctx.args)
    argv = ["--root", ctx.obj["root"], *extra]
    sys.exit(admin_main(argv))


if __name__ == "__main__":
    cli()
