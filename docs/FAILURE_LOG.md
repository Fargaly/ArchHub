# FAILURE_LOG

Append-only record of "shipped-but-invisible" claims, gaps the founder
caught, and how they were resolved. Established 2026-05-25 per
ROLLBACK-PROTOCOL mandate. Read at the start of every `/loop`
iteration so the same gap class doesn't recur.

Format per entry:

    | date | claim | gap found | resolution |

---

| date       | claim                                                                                 | gap found                                                                                                                  | resolution                                                                  |
|------------|----------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| 2026-05-25 | "D2·A 1/3 GraphHealthBadge shipped" (commit d772712)                                  | Visible in canvas but only in session view, not Home. Founder said "where are the nodes... none appeared in my app"        | AgDR-0043 workshop · Sprint 0+1 mandates user-visible default-view check    |
| 2026-05-25 | "D2·A 2/3 BrokenWireDialog shipped" (commit 58fb6c0)                                  | Modal renders but "Insert adapter" + "Swap downstream" buttons STILL disabled at studio-lm.jsx:6280 — D2·A 3/3 wired but dialog buttons never re-enabled | AgDR-0043 Sprint 2 · Move 6 (Cmd+K wires this) closes the loop              |
| 2026-05-25 | "AgDR-0041 status: executing → executed" (commit a27196e + others)                    | All 6 properties' BACKEND shipped but BrokenWireDialog adapter buttons disabled + 0 UI consumers exist for swap/freeze/bypass beyond the right-click context menu (low discoverability) | Workshop · Sprint 0 mandates UI-surface check before status flip                |
| 2026-05-25 | "D1·C 6/6 AgDR-0042 status: executing → executed" (commit a5d868b)                    | All 6 slices' BACKEND shipped (memory graph + 4 extractors + BFS query + community + sync) but ZERO JSX consumer. Founder cannot see his 197 nodes / 76 capabilities / 176 communities anywhere in the app. | Workshop · Sprint 2 Move 7 (memory-aware Library) renders the graph. Sprint 0 mandates UI-surface check before AgDR `executed`. |
| 2026-05-25 | "AgDR-0024 Host Node v2 shipped" + AgDR `status: executed`                            | Built but localStorage-gated OFF by default. No Settings UI toggle. Founder must open DevTools to enable. S2/S3 sub-slices explicitly missing per code comment.           | Sprint 2 · Settings UI exposes the toggle + sub-slices reopened              |
| 2026-05-25 | "AgDR-0021 ai.plan canvas node shipped" + AgDR `status: executed`                     | Engine registered, writes to disk. ZERO JSX references to `ai.plan` / `AiPlan` / plan history. Renders as generic palette tile. No replay button. No history viewer.       | Sprint 2 · Move 8 (ai.plan as hero node 2.5× size) per prototype contract   |
| 2026-05-25 | "AgDR-0022 ReactFlow scaffold" + ARCHITECTURE LOCK "ReactFlow is the canvas substrate" | ReactFlow NEVER installed. `NodeCanvasRF_Stub` is a placeholder that says "REACTFLOW CANVAS — PREVIEW · Migration ships across P2.a → P2.d". Direct contradiction of the locked architecture. | RESOLVED 2026-05-25 — AgDR-0045 supersedes AgDR-0012's ReactFlow lock + AgDR-0022 in full. Custom canvas is the substrate of record. Stub kept only for the existing test. |
| 2026-05-25 | "ship(archhub-redesign A): composer-first home" (commit 34ad75a) + "fix(home): explicit CSS order" (0aa8c32) | Composer moved from familiar bottom-fixed to top-of-page without founder approval. Founder: "do things deeply... won't fix something and fuck everything else up... why did you change the composer place?" Shipped Prototype A blindly without confirming the move was wanted; the followup order-fix patched a symptom of the same uncoordinated change. | Reverted both commits (537fab8 + 972962d). Composer back to `position:fixed bottom:80`. Don't ship layout moves from a prototype again without explicit per-section confirmation. |
