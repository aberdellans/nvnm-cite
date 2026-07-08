# NVNM Cite

### Verify your citations exist — and prove, permanently, that you checked.

---

## The problem

A brief can be derailed by a single citation that doesn't exist. Fabricated or
garbled cites — whether from a drafting error, a bad copy-paste, or an AI tool —
now draw sanctions, malpractice exposure, and reputational harm. Existing tools
either cost a fortune, lock your work into a proprietary database, or ask you to
trust a vendor's word that a check ever happened.

NVNM Cite does one thing, narrowly and verifiably: it confirms that every case
you cite is a **real, canonical citation**, and it gives you a tamper-proof
**receipt** proving you ran that check on a specific document at a specific time.

---

## What it does

**1. Checks citations against authoritative court registries.**
Your brief is parsed locally and each citation is matched against per-court
registries of canonical U.S. case citations, sourced from the Free Law Project's
CourtListener data. You see, cite by cite, what was found and what wasn't —
before you file.

**2. Anchors a filing receipt at the moment you file.**
When you're ready, NVNM Cite records a compact **receipt** on the NVNM Chain. The
receipt contains a fingerprint (SHA-256) of your exact document plus provenance —
when it was checked, against which court registries, and by whom. Anyone can
later re-run the same check and confirm the result. The record is append-only:
nothing can ever be erased or rewritten, and every version stays permanently
readable.

---

## What it deliberately does *not* do

This is **provenance, not truth**. NVNM Cite is precise about its boundaries:

- It **never** claims a case supports your proposition.
- It **never** asserts whether a case is still good law.
- It only answers one question — *does this citation exist as a canonical
  reference?* — and proves you asked it.

That narrow scope is the point: it's a verifiable fact you can stand behind, not
a black-box judgment you have to defend.

---

## Why it's different

- **Your citations stay in plaintext, and stay yours.** Citations are checked,
  never published. The only thing written to the chain is a hash of your
  document and minimal provenance — never the list of cases you cited, never the
  brief itself.
- **The receipt is independently verifiable.** A receipt binds the exact bytes
  of your document. A court, an opposing party, or a malpractice carrier can
  reproduce your verification without trusting NVNM — and without you handing
  over your work product.
- **You own your receipts.** Receipts live in a registry controlled by your
  firm's own wallet, on a per-case basis. NVNM is not a gatekeeper and cannot
  lock you out of your own filing record.
- **Open and auditable methodology.** The citation normalizer — the rules that
  decide what counts as a match — is openly specified and versioned, and every
  receipt records the version used. No moving the goalposts.
- **Corrections never rewrite history.** If a registry entry ever needs fixing,
  the fix is appended as a new version and the original stays permanently
  readable beside it. No silent edits.

---

## How it fits your workflow

1. **Draft** as you normally would.
2. **Check** your brief against the court registries — review found vs.
   not-found citations and fix issues before filing.
3. **File**, and at filing time anchor a receipt to the NVNM Chain.
4. **Keep** a permanent, reproducible record that you verified your citations on
   this exact document, at this exact time.

---

## In one line

> NVNM Cite confirms your citations are real and gives you a permanent,
> independently verifiable receipt that you checked — without ever publishing
> your brief or asserting anything it can't prove.

*Case data attribution: CourtListener / Free Law Project.*
