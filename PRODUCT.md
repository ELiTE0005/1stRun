# Product

## Register

brand

## Users

Founders, developers and docs leads who have never heard of FirstRun. They land on the homepage cold, often from a link in a post. They read for about 10 seconds before they decide whether to stay. They are technical, but they are not here to read logs, traces or a financial model.

## Product Purpose

FirstRun checks documentation by running it. Two tools:

- **Doc-test** runs a quickstart in a clean container, finds the first step that breaks, fixes the docs and proves the fix in a second clean run. This is the main action. A visitor should paste a docs URL and run it.
- **Doc-audit** reads a repo's history and lists which docs pages went stale and which shipped features have no docs.

Every run and every audit ends with a receipt: what it cost, which plan tier caps it, and the proof it passed. cfo.ai models the prices and caps. neatlogs traces every run. Entire records the build.

Success: a new visitor can say in one sentence what Doc-test does, what Doc-audit does, and why the result can be trusted, then try Doc-test.

## Brand Personality

Calm, precise, confident. Apple-like: light mode, real logos, dead simple, big type, one idea per screen, the fewest steps.

## Anti-References

- A page that reads like a log, a dashboard or a report. If a section needs the reader to decode it, it fails.
- Walls of text, long subtitles under headings, three claims in one paragraph.
- Mixing Doc-test and Doc-audit in the same section. Each gets its own section, its own background color, and its own proof.
- Identical card grids, hero-metric templates, gradient text, glassmorphism.
- Internal build trivia (trace ids, hashes, hackathon plumbing) on the main path.

## Design Principles

1. One section, one idea, one sentence of explanation.
2. Doc-test, Doc-audit and the receipt story each have a different background so a new reader always knows which tool they are reading about.
3. Show the thing, not a description of it: a real broken step, a real fix, a real receipt.
4. H2s are centered and have no subtitle. Links are always underlined. Content is centered unless a layout needs otherwise.
5. Real PRs, real repos, real logos beat claims.

## Accessibility & Inclusion

WCAG AA contrast. Honor `prefers-reduced-motion`. Never use color as the only signal. Underlined links. Works at 375 px wide with no sideways scroll.
