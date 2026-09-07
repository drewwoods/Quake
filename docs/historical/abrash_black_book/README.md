# Michael Abrash, *Graphics Programming Black Book* (Special Edition, 1997)

The complete book, mirrored from [jagregory/abrash-black-book](https://github.com/jagregory/abrash-black-book) — 70 chapters, appendices and all 196 figures.

Chapters 58–70 are the reason it is here. They were written at id Software during and just after Quake's development, and are the closest thing to a contemporaneous design record the engine has. The rest of the book is the foundation those chapters assume: it is what Abrash knew about squeezing x86 processors before Carmack recruited him in March 1995.

The Quake architecture guides under [`docs/architecture/`](../../architecture/) cite these chapters directly.

---

## Optimization mindset

How Abrash and Carmack think about performance work. Cited in spirit throughout the design history.

| Chapter | Title |
| :--- | :--- |
| [1](chapter-01.md) | The Best Optimizer Is between Your Ears |
| [2](chapter-02.md) | A World Apart |
| [3](chapter-03.md) | Assume Nothing |
| [7](chapter-07.md) | Local Optimization |
| [9](chapter-09.md) | Hints My Readers Gave Me |
| [10](chapter-10.md) | Patient Coding, Faster Code |
| [16](chapter-16.md) | There Ain't No Such Thing as the Fastest Code |
| [22](chapter-22.md) | Zenning and the Flexible Mind |

## Cycle-level x86

Where the cycles actually go on 286/386/486 and, critically, Pentium.

| Chapter | Title |
| :--- | :--- |
| [4](chapter-04.md) | In the Lair of the Cycle-Eaters |
| [5](chapter-05.md) | Crossing the Border |
| [6](chapter-06.md) | Looking Past Face Value |
| [8](chapter-08.md) | Speeding Up C with Assembly Language |
| [11](chapter-11.md) | Pushing the 286 and 386 |
| [12](chapter-12.md) | Pushing the 486 |
| [13](chapter-13.md) | Aiming the 486 |
| [19](chapter-19.md) | Pentium: Not the Same Old Song |
| [20](chapter-20.md) | Pentium Rules |
| [21](chapter-21.md) | Unleashing the Pentium's V-Pipe |
| [23](chapter-23.md) | Bones and Sinew |

## Algorithms and data structures

General technique, largely independent of the hardware chapters.

| Chapter | Title |
| :--- | :--- |
| [14](chapter-14.md) | Boyer-Moore String Searching |
| [15](chapter-15.md) | Linked Lists and plain Unintended Challenges |
| [17](chapter-17.md) | The Game of Life |
| [18](chapter-18.md) | It's a plain Wonderful Life |

## VGA and Mode X

EGA/VGA register programming. Historically important, but not load-bearing for Quake.

| Chapter | Title |
| :--- | :--- |
| [24](chapter-24.md) | Parallel Processing with the VGA |
| [25](chapter-25.md) | VGA Data Machinery |
| [26](chapter-26.md) | VGA Write Mode 3 |
| [27](chapter-27.md) | Yet Another VGA Write Mode |
| [28](chapter-28.md) | Reading VGA Memory |
| [29](chapter-29.md) | Saving Screens and Other VGA Mysteries |
| [30](chapter-30.md) | Video Est Omnis Divisa |
| [31](chapter-31.md) | Higher 256-Color Resolution on the VGA |
| [32](chapter-32.md) | Be It Resolved: 360x480 |
| [33](chapter-33.md) | Yogi Bear and Eurythmics Confront VGA Colors |
| [34](chapter-34.md) | Changing Colors without Writing Pixels |
| [43](chapter-43.md) | Bit-Plane Animation |
| [44](chapter-44.md) | Split Screens Save the Page Flipped Day |
| [45](chapter-45.md) | Dog Hair and Dirty Rectangles |
| [46](chapter-46.md) | Who Was that Masked Image? |
| [47](chapter-47.md) | Mode X: 256-Color VGA Magic |
| [48](chapter-48.md) | Mode X Marks the Latch |
| [49](chapter-49.md) | Mode X 256-Color Animation |

## Rasterization foundations

Lines, polygons, fills and anti-aliasing — the groundwork the Quake rasterizer assumes.

| Chapter | Title |
| :--- | :--- |
| [35](chapter-35.md) | Bresenham Is Fast, and Fast Is Good |
| [36](chapter-36.md) | The Good, the Bad, and the Run-Sliced |
| [37](chapter-37.md) | Dead Cats and Lightning Lines |
| [38](chapter-38.md) | The Polygon Primeval |
| [39](chapter-39.md) | Fast Convex Polygons |
| [40](chapter-40.md) | Of Songs, Taxes, and the Simplicity of Complex Polygons |
| [41](chapter-41.md) | Those Way-Down Polygon Nomenclature Blues |
| [42](chapter-42.md) | Wu'ed in Haste; Fried, Stewed at Leisure |

## X-Sharp: Abrash's own 3-D engine

The 3-D library Abrash built before joining id, and the thinking he brought with him.

| Chapter | Title |
| :--- | :--- |
| [50](chapter-50.md) | Adding a Dimension |
| [51](chapter-51.md) | Sneakers in Space |
| [52](chapter-52.md) | Fast 3-D Animation: Meet X-Sharp |
| [53](chapter-53.md) | Raw Speed and More |
| [54](chapter-54.md) | 3-D Shading |
| [55](chapter-55.md) | Color Modeling in 256-Color Mode |
| [56](chapter-56.md) | Pooh and the Space Station |
| [57](chapter-57.md) | 10,000 Freshly Sheared Sheep on the Screen |

## Quake

Written at id during and just after Quake's development. The primary source for the design history guide.

| Chapter | Title |
| :--- | :--- |
| [58](chapter-58.md) | Heinlein's Crystal Ball, Spock's Brain, and the 9-Cycle Dare |
| [59](chapter-59.md) | The Idea of BSP Trees |
| [60](chapter-60.md) | Compiling BSP Trees |
| [61](chapter-61.md) | Frames of Reference |
| [62](chapter-62.md) | One Story, Two Rules, and a BSP Renderer |
| [63](chapter-63.md) | Floating-Point for Real-Time 3-D |
| [64](chapter-64.md) | Quake's Visible-Surface Determination |
| [65](chapter-65.md) | 3-D Clipping and Other Thoughts |
| [66](chapter-66.md) | Quake's Hidden-Surface Removal |
| [67](chapter-67.md) | Sorted Spans in Action |
| [68](chapter-68.md) | Quake's Lighting Model |
| [69](chapter-69.md) | Surface Caching and Quake's Triangle Models |
| [70](chapter-70.md) | Quake: A Post-Mortem and a Glimpse into the Future |

## The Quake chapters in detail

The passages the design history leans on most:

| Chapter | What it establishes |
| :--- | :--- |
| [59](chapter-59.md) | BSP trees from first principles. Chapter 60 opens by continuing from here. |
| [60](chapter-60.md) | Building a BSP compiler; how Carmack recruited Abrash to id in March 1995. |
| [61](chapter-61.md) | Rotations, view coordinate systems, transformation matrices. |
| [62](chapter-62.md) | A working BSP renderer; the front-to-back traversal later chapters assume. |
| [63](chapter-63.md) | Floating point in a real-time loop — the x87 precision-control trick that halves `fdiv` latency. |
| [64](chapter-64.md) | **The PVS.** The beam tree, five discarded approaches, and precomputed visibility. |
| [65](chapter-65.md) | Near clip planes and view-frustum clipping. |
| [66](chapter-66.md) | The edge list, and the narrow role the z-buffer actually plays. |
| [67](chapter-67.md) | Span sorting benchmarked against the alternatives. |
| [68](chapter-68.md) | **Surface caching.** Separating high-frequency texture from low-frequency light. |
| [69](chapter-69.md) | Surface cache implementation, and Quake's triangle models. |
| [70](chapter-70.md) | Post-mortem, including the VQuake and GLQuake ports. |

Note: figure and chapter titles here are taken from the chapter files themselves. An
earlier version of this index carried several titles that did not match the text.

## Figures

`images/` holds all 196 figures the chapters reference, at the same paths the
markdown already uses, so every `![Figure 64.1](images/64-01.jpg)` resolves when a
chapter is read locally.

## Source & license

Mirrored from [jagregory/abrash-black-book](https://github.com/jagregory/abrash-black-book),
whose README states only: "Reproduced with blessing of Michael Abrash, converted and
maintained by James Gregory." The upstream repository carries no explicit licence file,
and no formal grant from Michael Abrash or the Coriolis Group is published there. Treat
this as a mirror held on the author's stated blessing rather than under a named open
licence, and check with upstream before redistributing.
