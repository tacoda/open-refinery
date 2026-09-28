## Why

<!-- The change is visible in the diff; the reason is not. Start here. -->

## What changed

<!-- One line per thing somebody reviewing this needs to hold in their head. -->

## Checklist

- [ ] `make test` is green
- [ ] Non-trivial logic lands with a test — and a bug was proved with a failing one first
- [ ] `make ui` is green, if the dashboard changed (`tsc -b`, not `tsc --noEmit`)
- [ ] A schema change ships its migration **and** its reverse in `DOWNGRADES`
- [ ] Docs updated if behaviour changed — `LIMITATIONS.md` too, if a boundary moved

<!--
Larger changes — a new pillar, a new dependency, a change to the policy engine
or the ladder — are worth an issue first. See CONTRIBUTING.md.
-->
