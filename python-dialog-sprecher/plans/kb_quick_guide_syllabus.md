# KB Quick Guide Syllabus

The reader should not need a live model call to understand the current Kannbeschreibung.
The UI should always expose a stable syllabus card for the active KB:

- original German KB;
- simplified German;
- simple English;
- scene and roles;
- task layout;
- core phrases;
- word bank;
- grammar tools;
- related KBs.

This replaces the first use case for the quiet note-taker. The note-taker can still exist later for richer reader notes, but it should be off by default because a static KB guide is cheaper, more consistent, and easier to edit.

Current seed coverage focuses on the text/list-to-mediation cluster:

- K084-K086 and K092/K104 for written/list comprehension;
- K163 as the general bridge from list/text to mediation;
- K173-K176 as sign/shop/restaurant/hotel variants.

Implemented UI direction:

- current KB card stays live beside the conversation;
- full KB syllabus browser is always available in the sidebar;
- browser search covers KB id, German text, simple English, scene, roles, words, grammar, and related KBs;
- related KB buttons jump inside the syllabus browser;
- "Put Kxxx in run box" prepares an individual run without auto-spending API calls.

Next work:

- extend `canon/kann_quick_guides.json` across all A1 KBs;
- add source/provenance notes for hand-built word banks;
- improve the fallback guides for KBs that do not yet have hand-built quick-guide entries;
- let expensive planning models fill candidate guides, then keep the edited JSON as the real product.
