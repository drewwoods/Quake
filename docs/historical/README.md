# id Software Historical Technical Archives

This directory preserves foundational technical writings, engine announcements, Usenet communications, daily development logs, and architectural documentation produced by **John Carmack** and the **id Software** team between **1993 and 2010**.

---

## Directory Index

```text
docs/historical/
├── README.md                     # This historical overview and master index
├── plans/                        # Developer .plan files (1994–2010, 494 files, 2.35 MB)
│   ├── README.md                 # Detailed index, finger protocol history, and developer bios
│   ├── carmack/                  # John Carmack daily logs (1996–2010, 441 files)
│   ├── john_romero/              # John Romero (1994–1997, 4 files)
│   ├── john_cash/                # John Cash (1996–1997, 6 files)
│   ├── brian_hook/               # Brian Hook (1997, hardware benchmarks)
│   ├── id_software_support/      # id Help Desk bulletins (1994–1996, 27 files)
│   └── ... (American McGee, Tim Willits, Christian Antkow, Dave Taylor, Jay Wilbur, etc.)
├── doom_1993/                    # 1993 DOOM engine technical announcements and retrospectives
│   ├── doom_press_release_1993.txt     # The original Jan 1, 1993 announcement and technical specification
│   └── carmack_doom_retrospective.txt  # John Carmack's retrospective on DOOM's 2D BSP and rendering limits
├── idnews/                       # 21 official id Software Usenet announcements (1993–1995)
│   ├── idNews01_dmxgus.ini.txt         # Gravis UltraSound setup & DMX sound library troubleshooting
│   ├── idNews03_release1.1.txt         # DOOM 1.1 release announcement & netplay fixes
│   ├── idNews06_help1.2_ports.txt      # Response to Unix/Linux/IRIX porting petitions
│   ├── idNews08_release1.2.txt         # DOOM 1.2 release announcement
│   ├── idNews14_release1.666.txt       # DOOM 1.666 release announcement (deathmatch 2.0)
│   ├── idTalks_released_1.4b.txt       # John Romero on DOOM 1.4 beta
│   ├── id_history.txt                  # John Romero on id Software's early founding history
│   └── ... (21 files total)
└── abrash_black_book/            # Michael Abrash's Graphics Programming Black Book
    ├── black-book.html                 # Jagregory's rendered complete book
    ├── book.css                        # Rendered book stylesheet
    └── images/                         # The book's figures
```

---

## 1. Developer `.plan` Files (1994–2010)
Folder: [`plans/`](plans/)

Accessible via the Unix `finger` protocol on id's NeXTSTEP and Unix servers, these files were the gaming industry's first daily developer blogs:
* **John Carmack**: 441 files spanning 1996 through 2010 (available as day-by-day logs, annual compilations, and raw multi-day finger snapshots) covering QTest, QuakeWorld, GLQuake, Quake II, Quake III Arena, Doom 3, and early id Tech 5.
* **John Romero**: March 1994 announcement of *"QUAKE: The Fight for Justice"* and 1997 Ion Storm retrospectives.
* **John Cash**: June–July 1996 daily crunch logs detailing the Quake menu rewrite, Win95 TCP/IP dial-up, IPX socket buffers, and modem/serial multiplayer.
* **Brian Hook**: December 1997 3D hardware benchmarking comparing the NVIDIA RIVA 128 AGP, Rendition Vérité V2200 AGP, and 3dfx hardware.
* **Support & Other Team Members**: 27 official help desk bulletins, alongside updates from American McGee, Tim Willits, Christian Antkow, Dave Taylor, Jay Wilbur, Shawn Green, and Barrett Alexander.

For complete developer bios, notable quotes, and technical context, see [`plans/README.md`](plans/README.md).

---

## 2. The 1993 DOOM Engine Specification & Announcement
Folder: [`doom_1993/`](doom_1993/)

On January 1, 1993, id Software issued its historic press release announcing *DOOM*. Drafted with Technical Director John Carmack, it marked the first time id articulated the architectural shift from grid-based raycasting (*Wolfenstein 3D*) to a general-purpose, non-orthogonal 3D engine:
* **Arbitrary-Angle Walls & Non-Orthogonal Geometry**: Allowing rooms of any shape and thickness.
* **Variable Heights**: Staircases, platforms, and varying floor/ceiling elevations.
* **Light Diminishing & Sourcing**: Simulating ambient darkness and localized illumination without hardware lighting.
* **Texture Mapping**: Texture-mapped floors and ceilings at 35 FPS on a 486/33.
* **Open Architecture Manifesto**: A commitment to release file formats and technical notes so the community could build custom tools.

Alongside the original press release is Carmack's retrospective written for the open-source release of the DOOM engine, analyzing the strengths and limitations of its 2D BSP tree, visplane generation, and collision routines.

---

## 3. Official id Software Usenet Bulletins (`idNews`, 1993–1995)
Folder: [`idnews/`](idnews/)

Before public `.plan` files existed, id Software maintained an active presence on Usenet newsgroups (`alt.games.doom`, `comp.sys.ibm.pc.games.action`, `rec.games.computer.doom.misc`). This archive, preserved from the canonical `gamers.org` repository, contains 21 official posts by **Dave Taylor**, **John Romero**, and **Jay Wilbur**:
* Real-time bug fixes and patch release notes (v1.1, v1.2, v1.666).
* Early network debugging for serial, modem, and IPX local area networks.
* The community petitions and id's decisions regarding SGI IRIX and Linux ports.
* Announcements of *The Ultimate DOOM* and *DOOM II*.

---

## 4. The 1995 Quake Architectural Breakthroughs (Michael Abrash)
Folder: [`abrash_black_book/`](abrash_black_book/)

In 1995, Carmack recruited Michael Abrash from Microsoft to id Software in Mesquite, Texas. Their collaboration produced the core architectural innovations of the *Quake* engine:
1. **Precomputed Potentially Visible Sets (PVS)**: Solved real-time 3D visible surface determination by precalculating inter-leaf visibility in `qbsp`.
2. **Surface Caching**: Carmack's realization that dynamic lighting could be applied to mipmapped textures in RAM once, avoiding per-pixel lighting in the rasterization loop.
3. **Sorted Spans**: Drawing polygons strictly front-to-back using the 3D BSP tree, guaranteeing zero overdraw in software rendering.

The complete rendered book is copied from
[jagregory/abrash-black-book](https://github.com/jagregory/abrash-black-book),
commit `e9812cc0fb641b87ab4e646affb1ed6c5508adee`. Architecture-guide links
target chapter and section anchors in [`black-book.html`](abrash_black_book/black-book.html).
