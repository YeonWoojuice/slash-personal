---
schema: omd.preferences/v1
design_md_hash_at_creation:
---

# Preference Log

## 2026-07-29T14:27:39.952Z — introduced-off-palette-color-s-ff5f5f-ff

```omd-meta
id: pref_ms66in1s_84f8d01d
timestamp: 2026-07-29T14:27:39.952Z
scope: color
signal: ambient
confidence: inferred
status: rejected
rejected_reason: "#ff5f5f no longer in code (superseded by canonical #ff4d4d stop); #ff9a3d/#ffd23d are the documented brand-gradient stops in DESIGN.md §2 — false positive"
source_agent: claude-code
source_context: "/Users/mimyo/projects/slash/slash-frontend/src/index.css"
```

Introduced off-palette color(s) #ff5f5f, #ff9a3d, #ffd23d in /Users/mimyo/projects/slash/slash-frontend/src/index.css — not in DESIGN.md

## 2026-07-29T14:30:37.764Z — introduced-off-palette-color-s-f7f7fb-ff

```omd-meta
id: pref_ms66mg90_4032b7a6
timestamp: 2026-07-29T14:30:37.764Z
scope: color
signal: ambient
confidence: inferred
status: rejected
rejected_reason: "these are the canonical light-theme Canvas/Surface/Surface Raised tokens documented in DESIGN.md §2 color table, not off-palette — false positive"
source_agent: claude-code
source_context: "/Users/mimyo/projects/slash/slash-frontend/src/index.css"
```

Introduced off-palette color(s) #f7f7fb, #ffffff, #eef0f6 in /Users/mimyo/projects/slash/slash-frontend/src/index.css — not in DESIGN.md

## 2026-07-29T14:41:29.707Z — introduced-off-scale-border-radius-round

```omd-meta
id: pref_ms670faj_611078ee
timestamp: 2026-07-29T14:41:29.707Z
scope: visualTheme
signal: ambient
confidence: inferred
status: rejected
rejected_reason: "SettingsDialog.tsx no longer uses rounded-md; now uses rounded-[8px], which is on the documented radius scale (DESIGN.md §5) — already resolved in code"
source_agent: claude-code
source_context: "/Users/mimyo/projects/slash/slash-frontend/src/components/SettingsDialog.tsx"
```

Introduced off-scale border radius rounded-md(6px) in /Users/mimyo/projects/slash/slash-frontend/src/components/SettingsDialog.tsx — not in DESIGN.md radius scale

## 2026-07-29T15:07:11.163Z — introduced-off-palette-color-s-ff4d4d-in

```omd-meta
id: pref_ms67xgor_3c06b6b0
timestamp: 2026-07-29T15:07:11.163Z
scope: color
signal: ambient
confidence: inferred
status: rejected
rejected_reason: "matches the canonical brand-gradient first stop documented in DESIGN.md §2; this flag predates that revision — false positive"
source_agent: claude-code
source_context: "/Users/mimyo/projects/slash/slash-frontend/src/index.css"
```

Introduced off-palette color(s) #ff4d4d in /Users/mimyo/projects/slash/slash-frontend/src/index.css — not in DESIGN.md

## 2026-07-29T15:23:36.568Z — introduced-off-scale-motion-duration-dur

```omd-meta
id: pref_ms68il14_ed309d5e
timestamp: 2026-07-29T15:23:36.568Z
scope: motion
signal: ambient
confidence: inferred
status: rejected
rejected_reason: "already documented as an intentional exception in DESIGN.md §15 Motion & Easing (live audio-level meter, not a state transition)"
source_agent: claude-code
source_context: "/Users/mimyo/projects/slash/slash-frontend/src/components/MicSettingsPopover.tsx"
```

Introduced off-scale motion duration duration-75(75ms) in /Users/mimyo/projects/slash/slash-frontend/src/components/MicSettingsPopover.tsx — not in DESIGN.md motion scale

## 2026-07-30T04:57:16.985Z — introduced-off-palette-color-s-4285f4-34

```omd-meta
id: pref_ms71kz3t_44ec3fda
timestamp: 2026-07-30T04:57:16.985Z
scope: color
signal: ambient
confidence: inferred
status: applied
applied_at: 2026-07-31T00:00:00.000Z
source_agent: claude-code
source_context: "/Users/mimyo/projects/slash/slash-frontend/src/features/auth/LoginPage.tsx"
```

Introduced off-palette color(s) #4285f4, #34a853, #fbbc05 in /Users/mimyo/projects/slash/slash-frontend/src/features/auth/LoginPage.tsx — not in DESIGN.md

## 2026-07-30T08:54:50.372Z — introduced-off-palette-color-s-333333-in

```omd-meta
id: pref_ms7a2h38_95be4bed
timestamp: 2026-07-30T08:54:50.372Z
scope: color
signal: ambient
confidence: inferred
status: rejected
rejected_reason: "source file is an ephemeral session scratchpad test file (Naver iframe check), not application code — not applicable to the design system"
source_agent: claude-code
source_context: "/private/tmp/claude-501/-Users-ryujun-yeong-projects-likelion-slash-slash-frontend/88d91d03-33e4-463d-99be-d62c54a792d7/scratchpad/naver-embed-test.html"
```

Introduced off-palette color(s) #333333 in /private/tmp/claude-501/-Users-ryujun-yeong-projects-likelion-slash-slash-frontend/88d91d03-33e4-463d-99be-d62c54a792d7/scratchpad/naver-embed-test.html — not in DESIGN.md

## 2026-07-31T08:08:38.998Z — introduced-off-palette-color-s-f8f9fa-fa

```omd-meta
id: pref_ms8nuxcm_c884fc77
timestamp: 2026-07-31T08:08:38.998Z
scope: color
signal: ambient
confidence: inferred
status: pending
source_agent: claude-code
source_context: "/Users/ryujun-yeong/projects/SLIPPECAT.github.io/assets/style.css"
```

Introduced off-palette color(s) #f8f9fa, #fafbfc, #212529 in /Users/ryujun-yeong/projects/SLIPPECAT.github.io/assets/style.css — not in DESIGN.md
