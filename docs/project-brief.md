# Project Lighthouse

**Problem**

> When someone asks how a solar system should be installed or set up, the right answer depends on where they are and what they’re installing. It takes the national rules, the local grid operator’s rules and the manufacturer’s manual together. Switzerland alone has about 600 grid operators, and their rules change without notice, so nobody can answer reliably outside the regions they know. At my previous company, one topic alone, how each operator remotely controls inverters, meant researching operator after operator.
>
> Solar is one case of a problem that every intermediary between rule-makers and clients has: payroll providers with cantonal tax rules, billing services with insurers’ rules, builders with municipal codes. They don’t write these rules, there are many versions of them, and they change on someone else’s schedule.

**What this project builds**

An assistant that answers from such documents already exists in this repository. What it lacks is any defence against a document being superseded: a publisher changes one online, or replaces it at a new address while the old one stays up, and the assistant keeps answering from the old version without anyone noticing.

This project covers everything that has to happen from the moment a new version exists until the assistant demonstrably answers from it.

*Done by the system*

- Notice that a document has changed, or that another document replaces it.
- Make the new version current where the case is clear.
- Retire the old version and keep it on record.
- Check that answers now rest on the current version, and list earlier answers that relied on the old one.
- Raise a flag for every case it cannot settle and every check it could not complete.

*Done by a person*

- Decide what is watched.
- Resolve the flagged cases.
- Re-confirm each source from time to time.

**How I’ll know it works**

| **Case** | **Expected** |
| --- | --- |
| Content changed at the same address | New version current, old one retired |
| Same content, different packaging | Nothing replaced, no flag |
| New version published elsewhere, old one still online | Flagged, with the candidate document |
| Source unreachable or moved | Flagged as a failed check |
| Source not confirmed for too long | Flagged |
| Question whose answer differs between versions | Answer from the current version only |
| A version is retired | Earlier answers that relied on it are listed |

Each real change is scored as caught, missed or false alarm.

**Not in this project**

- Fetching pages and detecting that something changed. Existing tools do that.
- Finding the sources for a new rule-maker.
- Improving how questions are answered.

**Limits**

- A replacement at a new address can only be inferred. Some will be missed; periodic re-confirmation is the backstop.
- “Current” means the latest version the system can see, not what the publisher intends.
- Shown in one field, on a small number of rule-makers.
- Test answers are checked by the author against the source text, not by a licensed expert.
