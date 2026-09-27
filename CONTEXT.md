# PerkWatch domain language

## Card

One card product/account scope, identified by a stable `card_id` in
`src/perk_watch/cards.json`, with the sign its exports use for statement credits.
Credits, transactions, and community tips always belong to a card.

## Catalog credit

A trackable, issuer-provided credit in the hand-checked catalog
(`src/perk_watch/catalog.json`), identified by a stable `benefit_id`. It has an
amount per period, a period (monthly, quarterly, semiannual, annual), and a
tracking mode: **auto** (detected from statement credit lines) or **manual**
(paid inside an app, so only the user can confirm it). Perks and protections
are not catalog credits.

## Credit pattern

A case-insensitive regex that recognises one catalog credit's statement credit
line (for example "Platinum Resy Credit"). A line must also have the card's
credit sign. A line matching several credits is a catalog error, never guessed.

## Period and period status

One calendar window of a credit (a month, quarter, half-year, or year). Each
period has an amount, the amount used, and one status:

- **used**: the full amount was credited or marked.
- **partial**: the period closed with some value used.
- **missed**: the period closed with nothing used.
- **pending**: the period closed, but statements don't yet cover 10 days past
  its end, so a late credit may still post.
- **unmarked**: a closed period of a manual credit the user hasn't confirmed.
- **at risk**: the current period has value left and few days remain (7
  monthly, 14 quarterly, 30 semiannual, 45 annual).
- **open**: the current period has value left and time to use it.

## Mark

The user's confirmation that a manual credit's period was used. Marks are the
application's only runtime write, stored in `PERKWATCH_DATA_DIR/user/profile.json`.

## Raw data

Manually collected, local-only source material for a card: issuer benefit
guides, transaction exports, and community tips. Raw data is never read by the
user-facing application.

## Prepared data

The normalized local SQLite model built from raw data and read by PerkWatch:
the official terms library (with embeddings for search), normalized
transactions, community tips, blurbs, and a preparation report.

## Community tip and blurb

A community tip is a short, source-linked paraphrase of public advice for one
catalog credit. It is a suggestion, never an official rule. A blurb is a one-
to two-sentence summary of a credit's tips, written once at preparation time.
