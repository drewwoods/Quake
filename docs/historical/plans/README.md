# id Software Team `.plan` File Archive

This directory contains a preserved collection of historical `.plan` files from John Carmack and key members of the **id Software** development team between 1994 and 2010.

---

## 1. Background: The Unix `finger` Protocol & `.plan` Files

In the 1990s, id Software's development environment was built upon NeXTSTEP workstations and later IRIX and Linux servers. Under Unix-like operating systems, the `finger` user information protocol ([RFC 742](https://datatracker.ietf.org/doc/html/rfc742) / [RFC 1288](https://datatracker.ietf.org/doc/html/rfc1288)) allowed anyone on the internet to query a remote server for user status:

```bash
finger carmack@idsoftware.com
finger johnr@idsoftware.com
```

When queried, the finger daemon returned user login details alongside the contents of two special files in the user's home directory: `.project` (a one-line summary) and `.plan` (a multiline text file).

Rather than using `.plan` merely as an office schedule, John Carmack and the id Software team turned their `.plan` files into public, unfiltered development diaries. Long before blogs, RSS feeds, or modern social media platforms existed, developers and gamers checked `finger` updates daily to track technical milestones, engine architecture debates, bug triage, hardware benchmarks, and studio culture.

---

## 2. Directory Structure

```text
docs/plans/
├── README.md                     # This documentation and historical index
├── carmack/                      # John Carmack's complete archive (441 files, 1996–2010)
│   ├── by_day/                   # 394 individual daily entries (e.g., johnc_plan_19960218.txt)
│   ├── by_year/                  # 14 annual compilation files (johnc_plan_1996.txt to 2010.txt)
│   └── raw_finger_dumps/         # 33 raw multi-day snapshots with original Unix finger headers
├── american_mcgee/               # American McGee (american@idsoftware.com, 1995–1997)
├── barrett_alexander/            # Barrett "Bear" Alexander (bear@idsoftware.com, 1997)
├── brian_hook/                   # Brian Hook (bwh@idsoftware.com, 1997)
├── christian_antkow/             # Christian Antkow (strife@idsoftware.com & strife@rogue-ent.com, 1995–1996)
├── dave_taylor/                  # Dave Taylor (ddt@idsoftware.com, 1995)
├── id_software_support/          # id Software Help Desk bulletins (help@idsoftware.com, 1994–1996, 27 files)
├── jay_wilbur/                   # Jay Wilbur (jayw@idsoftware.com, 1995)
├── john_cash/                    # John Cash (jcash@idsoftware.com, 1996–1997)
├── john_romero/                  # John Romero (johnr@idsoftware.com 1994–1995 & romero@ionstorm.com 1997)
├── shawn_green/                  # Shawn Green (shawng@idsoftware.com, 1997)
└── tim_willits/                  # Tim Willits (twillits@idsoftware.com, 1997)
```

---

## 3. Team Member Directory & Profiles

| Directory | Name & Email | Role at id Software | Date Range | Description & Key Topics |
| :--- | :--- | :--- | :--- | :--- |
| [`carmack/`](carmack/) | **John Carmack**<br>`johnc@idsoftware.com` | Lead Programmer & Co-founder | 1996–2010 | The complete daily devlog covering *Quake*, *QuakeWorld*, *GLQuake*, *Quake II*, *Quake III Arena*, *Doom 3*, and early *id Tech 5*. Topics include BSP trees, surface caching, client-side prediction, OpenGL vs Direct3D, multi-threading, and hardware driver issues. |
| [`john_romero/`](john_romero/) | **John Romero**<br>`johnr@idsoftware.com` | Lead Designer & Co-founder | 1994–1997 | Includes the legendary March 1994 `.plan` describing the future *Quake: The Fight for Justice*, NeXTSTEP development advocacy, and a 1997 Ion Storm reflection on Quake II map credits and design. |
| [`john_cash/`](john_cash/) | **John Cash**<br>`jcash@idsoftware.com` | Programmer | 1996–1997 | Detailed daily work logs during the final release push for *Quake* (June–July 1996): rewriting the entire in-game menu system, implementing Win95 TCP/IP and IPX networking, serial/modem multiplayer, and bug fixes. |
| [`brian_hook/`](brian_hook/) | **Brian Hook**<br>`bwh@idsoftware.com` | Programmer | 1997 | In-depth 3D graphics hardware benchmarking for *Quake II*, comparing the NVIDIA RIVA 128 AGP, Rendition Vérité V2200 AGP, and 3dfx Voodoo Graphics, analyzing fill-rate vs host-limited bottlenecks. |
| [`american_mcgee/`](american_mcgee/) | **American McGee**<br>`american@idsoftware.com` | Level Designer | 1995–1997 | Quake map design updates, community contest announcements, and humorous studio news updates. |
| [`tim_willits/`](tim_willits/) | **Tim Willits**<br>`twillits@idsoftware.com` | Level Designer / Lead Designer | 1997 | Level design updates for Quake mission packs, Quake II planning, and level design submissions. |
| [`christian_antkow/`](christian_antkow/) | **Christian Antkow**<br>`strife@idsoftware.com` | Developer & Community Liaison | 1995–1996 | Updates covering the development of *Strife* (Rogue Entertainment / Doom engine) and id Software technical updates. |
| [`dave_taylor/`](dave_taylor/) | **Dave Taylor**<br>`ddt@idsoftware.com` | Programmer | 1995 | Unix/Linux/IRIX porting, multiplayer networking, and developer notes. |
| [`jay_wilbur/`](jay_wilbur/) | **Jay Wilbur**<br>`jayw@idsoftware.com` | Business Manager / CEO | 1995 | Company operational announcements and distribution notes. |
| [`barrett_alexander/`](barrett_alexander/) | **Barrett "Bear" Alexander**<br>`bear@idsoftware.com` | Level Designer | 1997 | Quake II design updates and development progress. |
| [`shawn_green/`](shawn_green/) | **Shawn Green**<br>`shawng@idsoftware.com` | Designer & Support | 1997 | Tech support triage and development notes. |
| [`id_software_support/`](id_software_support/) | **Help Desk**<br>`help@idsoftware.com` | Technical Support | 1994–1996 | 27 official technical support updates documenting patch releases (v1.2, v1.666), sound card compatibility (Gravis UltraSound, Sound Blaster), modem configuration strings, network protocols, and the Quake launch. |

---

## 4. Notable Historical Entries

### 1. The Genesis of Quake: John Romero (March 18, 1994)
File: [`john_romero/1994-03-18.txt`](john_romero/1994-03-18.txt)
> *"THE PLAN: To get the entire world running NEXTSTEP for development, get everyone connected on the Internet, and own a Testarossa TR512... The next game is going to blow DOOM all to hell. DOOM totally sucks in comparison to our next game, QUAKE: The Fight for Justice! QUAKE is going to be a bigger step over DOOM than DOOM was over Wolf3D..."*

### 2. The Final Push for Quake: John Cash (June–July 1996)
File: [`john_cash/1996-07-09.txt`](john_cash/1996-07-09.txt)
A rare, day-by-day diary of Quake's launch crunch, including:
- Rewriting the entire menu hierarchy from scratch to replace raw console inputs
- Debugging Win95 TCP/IP dial-up networking and IPX socket buffers
- Setting standard VGA mode 13h as the safe default
- Integrating John Carmack's engine changes into the main branch

### 3. QTest & Quake Engine Foundations: John Carmack (February 1996)
File: [`carmack/by_day/johnc_plan_19960218.txt`](carmack/by_day/johnc_plan_19960218.txt) & [`carmack/by_year/johnc_plan_1996.txt`](carmack/by_year/johnc_plan_1996.txt)
> *"This is my daily work, starting about a week before qtest was released. When I accomplish something, I write a `*` line that day. Whenever a bug / missing feature is mentioned during the day and I don't fix it, I make a note of it... Occasionally I go back through the old notes and mark with a `+` the things I have since fixed."*

### 4. 3D Accelerator Benchmarking Wars: Brian Hook (December 15, 1997)
File: [`brian_hook/1997-12-15.txt`](brian_hook/1997-12-15.txt)
Benchmark comparisons between the NVIDIA RIVA 128 AGP, Rendition Vérité V2200 AGP, and 3dfx hardware for *Quake II*, analyzing fill-rate vs host-limited bottlenecks in early hardware 3D pipelines.

---

## 5. Sources & Provenance

These files are preserved from the following primary historical archives:
1. **Gamers.org .plans Archive**: Maintained at [gamers.org/pub/archives/plans/](https://www.gamers.org/pub/archives/plans/) preserving original finger captures and id Software developer snapshots.
2. **ESWAT John Carmack .plan Archive**: Curated by [ESWAT](https://github.com/ESWAT/john-carmack-plan-archive) and mirrored from Andrew's [floodyberry.com](http://floodyberry.com/carmack/plan.html) / `team5150.com` archive.

---

## 6. Pre-1996 Technical Communications

For technical communications, engine announcements, and architectural documentation created prior to the start of the `.plan` format in February 1996, see the sibling archives in [`docs/historical/`](../):
* [`doom_1993/`](../doom_1993/): The 1993 DOOM engine specification press release and Carmack's retrospective.
* [`idnews/`](../idnews/): 21 official id Software Usenet announcements (1993–1995).
* [`abrash_quake_1995/`](../abrash_quake_1995/): Michael Abrash's documentation of Quake's engine development with John Carmack in 1995.


