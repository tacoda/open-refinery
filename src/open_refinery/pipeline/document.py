"""The run document — the interface between stages, and the pull request body.

Each stage appends a section as it goes, so by the time a person reads the pull
request the account of the work is **already written**: what was asked, what was
planned, what was built, what was proved, what review found. Nothing is
summarised into existence at the end.

`requires` / `produces` on a stage (see `spec.py`) are sections of this
document, which is why they are strings rather than an enum: a team that adds a
`threat-model` stage producing `threat-model` needs no change here.

Pure — a document is text, and every function returns a new one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The order sections appear in, whatever order they were produced. A reader
# wants the story, not the schedule.
ORDER = ("spec", "plan", "work", "proof", "review", "notes")

TITLES = {
    "spec": "What was asked",
    "plan": "What was planned",
    "work": "What was built",
    "proof": "What was proved",
    "review": "What review found",
    "notes": "Notes",
}

_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Document:
    """An accumulating account of one run."""

    sections: dict[str, str]

    def has(self, name: str) -> bool:
        return bool(self.sections.get(name, "").strip())

    def get(self, name: str) -> str:
        return self.sections.get(name, "")

    def keys(self) -> tuple[str, ...]:
        return tuple(k for k in ORDER if self.has(k)) + tuple(
            k for k in self.sections if k not in ORDER and self.has(k))

    def with_section(self, name: str, body: str) -> Document:
        """A stage's output, replacing whatever was there.

        Replacing rather than appending is deliberate: a revision re-runs a
        stage, and two contradictory `What was built` sections is worse than
        either of them.
        """
        return Document({**self.sections, name: str(body or "").strip()})

    @property
    def text(self) -> str:
        parts = []
        for name in self.keys():
            parts += [f"## {TITLES.get(name, name)}", "", self.sections[name], ""]
        return "\n".join(parts).strip() + "\n" if parts else ""


def start(spec: str = "") -> Document:
    """A new document, from the spec the run was asked for."""
    return Document({"spec": str(spec or "").strip()} if spec else {})


def read(text: str) -> Document:
    """Parse a document back from its text — for a run resumed after a restart."""
    by_title = {title: key for key, title in TITLES.items()}
    sections: dict[str, str] = {}
    matches = list(_HEADING.finditer(text or ""))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(1).strip()
        sections[by_title.get(title, title)] = text[m.end():end].strip()
    return Document(sections)


def satisfied(doc: Document, requires) -> tuple[str, ...]:
    """Which of `requires` this document does not yet have."""
    return tuple(name for name in requires if not doc.has(name))
