"""The ``/`` command registry, modelled on the OpenCode TUI's.

A command is an id, a name, a description, a category (which groups it in
the palette), optional aliases and whether it takes an argument. The palettes
are generated from this table, so a command exists in exactly one place —
the way OpenCode drives its composer autocomplete and its Ctrl+P palette
from one keymap.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """One interface command."""

    id: str
    name: str
    description: str
    category: str = "Interface"
    aliases: tuple[str, ...] = ()
    arguments: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


#: Everything the interface can do. Nothing here touches the kernel directly:
#: commands are handled by the app, which is the only thing that owns a run.
COMMANDS: tuple[Command, ...] = (
    Command("interface.help", "help", "key bindings and what the harness enforces"),
    Command("session.new", "new", "start a fresh run", "Session"),
    Command("session.clear", "clear", "clear the transcript", "Session"),
    Command("harness.status", "status", "kernel, session and override state", "Harness"),
    Command("harness.gates", "gates", "the gates that decide what may happen", "Harness"),
    Command(
        "harness.tools",
        "tools",
        "tools exposed at the current step",
        "Harness",
    ),
    Command("harness.demo", "demo", "re-run the flow on the canned model", "Harness"),
    Command("tools.import", "import", "scan other agents' MCP servers and skills", "Tools"),
    Command(
        "model.show",
        "model",
        "the configured model and backend",
        "Model",
        aliases=("models",),
    ),
    Command("interface.palette", "palette", "every command, with its shortcut", "Interface"),
    Command("interface.quit", "quit", "leave the interface", "Interface", aliases=("exit", "q")),
)


def resolve(name: str) -> Command | None:
    """A command by name or alias, or None."""
    wanted = name.strip().lower()
    return next(
        (command for command in COMMANDS if wanted in command.names),
        None,
    )


def by_id(command_id: str) -> Command | None:
    """A command by its id (what the popups carry), or None."""
    return next((command for command in COMMANDS if command.id == command_id), None)


def match(query: str) -> list[Command]:
    """Commands for a ``/query`` prefix: name-prefix matches first.

    Ranking mirrors the composer autocomplete: the command whose name starts
    with what was typed comes first, then name substring, then description,
    so ``/he`` surfaces ``help`` before ``palette``.
    """
    term = query.strip().lower()
    if not term:
        return list(COMMANDS)
    prefixed = [c for c in COMMANDS if any(n.startswith(term) for n in c.names)]
    in_name = [c for c in COMMANDS if c not in prefixed and any(term in n for n in c.names)]
    described = [
        c
        for c in COMMANDS
        if c not in prefixed and c not in in_name and term in c.description.lower()
    ]
    return prefixed + in_name + described
