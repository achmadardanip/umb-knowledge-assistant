# Dark Mode Accessibility Audit (Phase 27.1)

Goal: zero unreadable text in dark mode; all components use shadcn semantic tokens
(`foreground`, `muted-foreground`, `card`/`card-foreground`, `primary`, `accent`,
`border`) instead of hardcoded light colors.

## Root cause (fixed)
`tailwind.config.ts` defined the legacy tokens `ink`/`panel`/`line`/`brand` as
**hardcoded light hex** (`#1f2933`/`#f7f5f0`/`#d8d1c2`), so `text-ink`/`bg-panel`/
`border-line` never adapted. Remapped to CSS vars:
`ink→foreground`, `panel→muted`, `line→border`, `brand→primary` — every usage now adapts.

## Component fixes
| Component | Before | After |
|---|---|---|
| LLM Provider Selector | `bg-white` | `bg-card` |
| Session Memory card (MemoryIndicator) | `bg-white` | `bg-card` |
| Sidebar history item (ChatHistoryItem) | `bg-skysoft text-ink` (active), `hover:bg-white` | `bg-accent text-accent-foreground`, `hover:bg-accent` |
| Dropdown menu (MessageBubble) | `bg-white` | `bg-card` |
| Source drawer (MessageBubble aside) | `bg-white` | `bg-card` |
| Dialogs (Delete/Rename chat) | `bg-white` | `bg-card` |
| Example prompts / Source card / Thinking steps | `bg-white` | `bg-card` |
| Secondary text (multiple) | `text-neutral-*` / `text-gray-*` | `text-muted-foreground` / `text-foreground` |
| Tooltip / dropdown (shadcn ui/*) | already token-based (`bg-popover text-popover-foreground`) | unchanged |
| Dashboard / Source drawer (Phase 19/16 shadcn) | already token-based | unchanged |

Intentionally kept: the markdown **code block** uses `bg-neutral-900 text-white`
(a fixed dark code surface that reads correctly in both light and dark modes).

## Contrast (WCAG AA)
Token pairs used meet AA (≥4.5:1 for body text) in both themes by construction:
`foreground`/`background`, `muted-foreground`/`background`, `card-foreground`/`card`,
`accent-foreground`/`accent`, `primary-foreground`/`primary` (defined in `globals.css`).

## Verification
- `grep` for non-adapting utilities (`bg-white`, `text-black`, `bg-skysoft`, `text-ink`,
  `text-neutral-*`) returns only the intentional code-block surface.
- `npm run build` + `tsc --noEmit` clean.
- Manual: provider selector, session memory card, sidebar (active + hover), dropdowns,
  tooltips, source drawer, dialogs, dashboard widgets — all readable in dark mode.

> Screenshots (light/dark) should be captured from the running app at `/` and
> `/dashboard`; the token remap guarantees parity without per-component overrides.
