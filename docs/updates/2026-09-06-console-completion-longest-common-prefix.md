# 6 Sep — Console Tab Completion: Longest Common Prefix & Option Listing

Currently, pressing `TAB` in the Quake console triggers `Cmd_CompleteCommand` followed by `Cvar_CompleteVariable`, which immediately autocompletes the line to the first match found (linked-list registration order) and appends a space. If multiple commands or variables match, other candidates cannot be discovered or completed without typing further characters.

This plan adds Quake 3-style tab completion (also `bash` with `show-all-if-ambiguous`):

1. Autocomplete only the **longest common prefix** (LCP) shared by all matching candidates.
2. If there is a **single unique match**, complete the full name with a trailing space.
3. If there are **multiple matches**, extend the line to the LCP (no trailing space) **and** print every candidate in column-major order. A later TAB at the same prefix prints the list again. This is not stock bash (which lists only on a second TAB); it is the better console behavior because there is no bell.

This plan is **WinQuake only** (`WinQuake/Makefile.macos`). QW already has a `CompleteCommand` in `QW/client/keys.c` that forces a leading `/` for command-vs-chat; a later plan can replace QW's first-match completer without copying WinQuake's slash rules.

---

## Key Decisions

1. **Prompt echo (Option A)**: On multiple matches, after applying any LCP extension, echo the current input line with `Con_Printf ("%s\n", key_lines[edit_line]);` (same form as Enter at `keys.c:167`), then print the columns. Scrollback shows why the list appeared.
2. **WinQuake only**: Do not touch QW in this change. QW's existing `CompleteCommand` skips `\`/`/`, writes `key_lines[edit_line][1] = '/'`, and `Cmd_CompleteCommand` already walks aliases. Mirroring WinQuake blindly would break QW chat.
3. **Include aliases**: `Cmd_CompleteCallback` walks `cmd_functions` **and** `cmd_alias`. Stock WinQuake omitted aliases; QW already includes them; `Cmd_ExecuteString` already executes them. After case-insensitive sorting and deduplication, the list shows each spelling-equivalent name once. Which spelling survives is unspecified because `qsort` is not stable.
4. **Case-insensitive match, canonical write-back**: Stock completion uses case-sensitive `Q_strncmp`. Command execution is case-insensitive (`Q_strcasecmp`); **cvar lookup is case-sensitive** (`Cvar_FindVar` uses `Q_strcmp`). Match with `Q_strncasecmp`. Compute LCP on folded case. Always copy bytes from a real match (the first after sort), even when the LCP is no longer than the typed prefix, so `R_D` + TAB canonicalizes to `r_d` and `R_DRA` + TAB becomes `r_draw` before Enter finds the cvar.
5. **No slash special case**: WinQuake Enter sends `key_lines[edit_line]+1` to `Cbuf_AddText`, so a slash-prefixed completion would produce a command token such as `/god` that `Cmd_ExecuteString` cannot run. Treat `/` and `\` as ordinary input; do not strip, preserve, normalize, or insert them. Slash-prefixed input therefore produces no matches.
6. **Empty prompt is a no-op**: Already true in stock (`Cmd_CompleteCommand` returns `NULL` when `len == 0`). Keep it, so a stray TAB does not dump ~278 registered command/cvar names.
7. **No argument completion**: A space in the token means the user is already past the command name. Leave the line alone (`map e1` does not complete).

---

## Proposed Changes

Grouping changes by subsystem: command discovery, cvar discovery, and key/input handling.

### Command & Cvar Subsystems

`cmd_functions` is `static` in `cmd.c`, so keys.c cannot walk commands itself. `cmd_alias` and `cvar_vars` are already visible; a matching callback on both sides keeps the enumerator in one shape.

#### [MODIFY] [cmd.h](../../WinQuake/cmd.h)

- Declare `void Cmd_CompleteCallback (char *partial, void (*callback)(char *name));` so callers can enumerate matching commands and aliases without leaking the linked lists.

#### [MODIFY] [cmd.c](../../WinQuake/cmd.c)

- Implement `Cmd_CompleteCallback`:
  - If `partial` is empty, return without calling `callback` (same empty rule as `Cmd_CompleteCommand`).
  - Iterate `cmd_functions` then `cmd_alias`.
  - Case-insensitive prefix match with `Q_strncasecmp (partial, name, len)` (`Q_strncasecmp` is an equality test: 0 vs -1. That is correct here).
  - Invoke `callback (name)` for each match. `name` points at the live command/alias string; the callback must not free it.
- Leave `Cmd_CompleteCommand` unchanged. After TAB is rerouted it is unused (`keys.c` is the only caller), but it is not this PR's job to delete it.

#### [MODIFY] [cvar.h](../../WinQuake/cvar.h)

- Declare `void Cvar_CompleteCallback (char *partial, void (*callback)(char *name));`.

#### [MODIFY] [cvar.c](../../WinQuake/cvar.c)

- Implement `Cvar_CompleteCallback` the same way over `cvar_vars`.
- Leave `Cvar_CompleteVariable` unchanged.

Engine commands and cvars cannot share an exact name (`Cmd_AddCommand` / `Cvar_RegisterVariable` both reject overlap). An alias may collide with a command. After case-insensitive sorting and deduplication, the list shows the name once; which spelling survives is unspecified because `qsort` is not stable. The current macOS build registers 132 commands and 146 cvars (278 total, before aliases).

---

### Input & Line Editing Subsystem

#### [MODIFY] [keys.c](../../WinQuake/keys.c)

`quakedef.h` already includes `<stdlib.h>`, so `qsort` is available. WinQuake has never used it; this is the first call site.

**Do not pass `Q_strcasecmp` to `qsort`.** `Q_strcasecmp` / `Q_strncasecmp` in `common.c` return only 0 or -1. That is not a three-way order, and `qsort` with it is undefined.

Keep the file-scope completion helpers in `keys.c` `static`, including `Complete_CharFold`, `Complete_NameCmp`, `Complete_SortDedup`, `Complete_LCPLength`, and `Complete_PrintColumns`. The throwaway harness copies the pure helper bodies; it does not link `keys.c`, so no exported contracts are needed. They take no engine types except `Con_Printf` in the printer.

##### `Complete_CharFold` / `Complete_NameCmp`

ASCII fold (`A–Z` → `a–z`) and a real `qsort` comparator on `char **`:

```c
static int Complete_CharFold (int c)
{
	if (c >= 'A' && c <= 'Z')
		return c + ('a' - 'A');
	return c;
}

static int Complete_NameCmp (const void *a, const void *b)
{
	const unsigned char *s1 = *(const unsigned char * const *)a;
	const unsigned char *s2 = *(const unsigned char * const *)b;

	while (*s1 && Complete_CharFold(*s1) == Complete_CharFold(*s2))
	{
		s1++;
		s2++;
	}
	return Complete_CharFold(*s1) - Complete_CharFold(*s2);
}
```

Do not use libc `strcasecmp` here: WinQuake still builds with MSVC `stricmp` on Windows and the Q_* helpers are equality-only. A local three-way compare is portable C89.

##### `static int Complete_SortDedup (char **names, int n)`

- `qsort (names, n, sizeof(char *), Complete_NameCmp);`
- Collapse adjacent names with `Complete_NameCmp == 0` (pointer-stable; keep the first).
- Return the new count.

##### `static int Complete_LCPLength (char **names, int n)`

- Case-insensitive. After sort, the LCP of the whole set is the LCP of `names[0]` and `names[n-1]`.
- Return how many bytes of `names[0]` are in that prefix (so the caller copies `names[0][0 .. len)` and gets canonical case).

##### `static void Complete_PrintColumns (char **names, int n, int linewidth)`

`Con_Print` word-wraps on spaces. A row of exactly `linewidth` characters followed by `\n` also emits a blank line (`con_x` wraps to 0, then `\n` linefeeds again). Do not dump a space-separated blob.

- `col_width = max_item_len + 2`
- `ncols = linewidth / col_width`; if `ncols < 1`, `ncols = 1` (one name per line). Never divide into zero columns.
- `nrows = (n + ncols - 1) / ncols`
- Column-major: `idx = col * nrows + row` (alphabetical down columns, like `ls -C`).
- For each row, pad every column except the last on that row to `col_width` with `%-*s`; the last column is the raw name. That keeps the row **strictly shorter** than `linewidth`, so `Con_Printf ("%s\n", line)` cannot trigger the blank-line wrap.
- Build the row in a stack buffer of 256 (or `MAXCMDLINE`); `con_linewidth` is `(vid.width >> 3) - 2` and is 38 until video init.

##### `void CompleteCommand (void)`

1. **Extract prefix**. `s = key_lines[edit_line] + 1` (skip `]`). Do not special-case a leading `/` or `\`; it remains part of the token and will normally produce no matches.
2. **Validate**. If `s` is empty (bare prompt) or `s` contains a space, return. Do not look at text after a space; this is command-name completion only.
3. **Collect matches**. Static `char *matches[1024]`. A file-scope collector appends `callback`'s `name` until 1024, then sets a `truncated` flag and drops further names. Call `Cmd_CompleteCallback` then `Cvar_CompleteCallback`. 1024 is well above the current macOS engine command+cvar count (278); the cap exists for a huge alias list from a config.
4. **Sort & dedup** via `Complete_SortDedup`.
5. **Branch on count**:
   - **0**: return. Line unchanged.
   - **1**: Rewrite the line as `]` + the match + `' '` + `NUL`. Set `key_linepos` accordingly. Names are far shorter than `MAXCMDLINE` (256); alias names are `< 32`.
   - **>1**:
     - If not `truncated`, `len = Complete_LCPLength (...)`. Copy `matches[0][0..len)` after `]` (no trailing space) and update `key_linepos` even when `len` equals the typed prefix. This both extends the LCP and canonicalizes case.
     - If `truncated`, do **not** extend the LCP (the omitted names could shorten it). Still list the 1024 kept names.
     - `Con_Printf ("%s\n", key_lines[edit_line]);` (echo after any LCP write).
     - `Complete_PrintColumns (matches, n, con_linewidth);`

In `Key_Console (int key)`: replace the current `if (key == K_TAB)` block with `CompleteCommand (); return;`.

---

## Names that tests must use

These are the names in the macOS software build (`Makefile.macos` does not define `QUAKE2`, so `changelevel2` is absent; `r_dspeeds` is registered in `r_main.c`).

| Typed | Matches | LCP written back |
|---|---|---|
| `ch` | `changelevel`, `chase_active`, `chase_back`, `chase_right`, `chase_up` | `cha` |
| `chase` | the four `chase_*` cvars | `chase_` |
| `chase_a` | `chase_active` | `chase_active ` (trailing space) |
| `r_d` | `r_dspeeds`, `r_drawentities`, `r_drawflat`, `r_draworder`, `r_drawviewmodel` | `r_d` (already the LCP) |
| `R_D` | same five `r_d*` names | `r_d` (canonicalized even though the LCP length is unchanged) |
| `r_dra` | the four `r_draw*` cvars | `r_draw` |
| `R_DRA` | same four, case-insensitive match | `r_draw` (canonical bytes from the cvar name) |
| `xyz` | none | unchanged |

Do not use `ch` → `chase_` or `r_d` → `r_draw`. Both are wrong on this engine.

---

## Verification Plan

### Automated tests

1. **Compilation**:
   ```bash
   make -C WinQuake -f Makefile.macos
   ```
   Zero errors. Do not claim zero warnings from this makefile: it does not pass `-Wall`. The harness below does.

2. **Throwaway harness** `/tmp/quake-test-tab-complete.c`:
   Compiles **only** the pure helpers (`Complete_NameCmp`, `Complete_SortDedup`, `Complete_LCPLength`, `Complete_PrintColumns` with a capture callback instead of `Con_Printf`). It does not link `keys.c` or the engine. Throwaway: not added to `Makefile.macos`. Keep the helper bodies in `keys.c` and copy the same bodies into the harness while implementing so the contracts cannot drift.

   ```bash
   cc -std=gnu89 -Wall -Wextra /tmp/quake-test-tab-complete.c -o /tmp/quake-test-tab-complete && /tmp/quake-test-tab-complete
   ```

   | # | Case | Expect |
   |---|---|---|
   | 1 | Unique name `chase_a` among `{chase_active, chase_back, …}` | LCP / single-match path yields `chase_active`; caller adds the trailing space |
   | 2 | `r_d` among the five `r_d*` names above | LCP length 3 (`r_d`); no extension |
   | 3 | `r_dra` among the four `r_draw*` names | LCP `r_draw` |
   | 4 | `r_draw` among the four `r_draw*` names | LCP `r_draw`; already at prefix |
   | 5 | Dedup `{god, god}` after sort | count 1 |
   | 6 | Mixed-case input `R_D` vs lowercase names: LCP of `{r_dspeeds, r_drawentities, …}` | bytes taken from `names[0]` after sort (`r_d`), not `R_D`, even though the length is unchanged |
   | 7 | `Complete_NameCmp` order: `r_dspeeds` before `r_drawentities` | three-way compare, not `Q_strcasecmp` |
   | 8 | Columns at `linewidth = 38` and `78` | column-major; each captured row strictly shorter than `linewidth`; `ncols` clamped to ≥ 1 when `col_width > linewidth` |
   | 9 | Folded LCP of `{FooBar, foobar}` | length 6, bytes from the first after sort |

   Argument-skipping (`map e1`) and empty-prefix no-op live in `CompleteCommand`, not the helpers. Cover those in manual tests.

### Manual verification

From the repository root, launch `./WinQuake/build/macos/release/quake` and open the console with `~`:

1. `ch` + TAB → line becomes `]cha`; scrollback has `]cha` then five names in columns (`changelevel` and the four `chase_*`).
2. TAB again → line stays `]cha`; the list prints again.
3. Type `se` (now `]chase`) + TAB → `]chase_`; four `chase_*` names.
4. Type `a` (now `]chase_a`) + TAB → `]chase_active ` with a trailing space; no list.
5. `xyz` + TAB → nothing changes; no list.
6. `r_d` + TAB → line stays `]r_d`; five names including `r_dspeeds`.
7. `R_D` + TAB → line becomes `]r_d`; the same five names print, proving canonicalization even without LCP extension.
8. `r_dra` + TAB → `]r_draw`; four `r_draw*` names.
9. `R_DRA` + TAB → `]r_draw` (canonical case), same list.
10. Empty prompt + TAB → no-op.
11. `map e` + TAB → no-op (space in the line).
12. `r_` + TAB → 21 matching `r_*` commands and cvars in columns; rows aligned; no extra blank lines from wrap.
