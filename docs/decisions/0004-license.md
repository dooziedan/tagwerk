# 0004: License AGPL-3.0-or-later
Date: 2026-10-03 · Status: Accepted

## Context
The repository is public. Tagwerk is a web app, and its tagging library mutagen is GPL-2.0-or-later, as is the wider ecosystem (Navidrome GPL-3.0, Picard GPL-2.0+). The owner wants improvements to stay open, including in hosted versions.

## Decision
License the project under the **GNU AGPL-3.0-or-later**. The "or later" wording follows the FSF's recommendation and keeps the option of future license versions.

## Consequences
- Anyone may use, modify and redistribute Tagwerk. Modified versions must stay AGPL. That includes versions offered to others over a network, whose users must be able to get the source (section 13). The page footer links to the source code for this reason.
- Compatible with the GPL-licensed mutagen and with permissive dependencies (MIT, BSD, Apache-2.0).
- Outside contributions are accepted under the same license (inbound = outbound).
- Companies that avoid AGPL software may not adopt it. That's acceptable for a self-hosted hobby project.
