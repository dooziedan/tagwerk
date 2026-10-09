# 0026: Mix names with capital letters
Date: 2026-10-09 · Status: Accepted

## Context
Many titles in the owner's library write the mix name in lower case: "Rio (club remix)", "Body (radio edit)". DJs and stores write "(Club Remix)", "(Radio Edit)". The inbox already proposed this clean-up for new tracks (`proposals.capitalise_mix_types`), but tracks already in the library never got it.

## Decision
- A **Mix names** page lists every library track whose title the rule would change, old → new, all ticked. "Create pending changes" stages the new titles (source "Mix names capitalised"); writing goes through review → apply as always. Final tracks are skipped, and a title change that is already pending is built on.
- One rule for the inbox and the library: track types inside brackets ("Remix", "Edit", "Re-Edit", "Bootleg", "VIP", ...) get their usual spelling. A bracket is only touched when it names a mix: it contains a mix word ("remix", "edit", "dub", ...) or consists only of track types ("(extended)", "(dirty intro)"). Brackets starting with "feat." or "with" name artists and are left alone, and so are words written in CAPITALS.
- Home shows the number of such tracks under "Worth a look", linking to the page (which lists exactly those tracks).
- Only the title tag. Mix names outside brackets ("Title - club mix") are not touched: there the dash may as well separate artist and title.

## Consequences
- Scans still store titles as found; nothing changes in the files without the owner's OK.
- A remixer whose name is a track type ("(dub remix)" by an artist called Dub) gets a capital letter too; the owner unticks it.
