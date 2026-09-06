# Michael Abrash: The Invention of the Quake Engine (1995–1996)

These chapters are from **Michael Abrash’s Graphics Programming Black Book** (Special Edition, 1997), documenting the collaboration between Michael Abrash and **John Carmack** during 1995–1996 to build the world's first true real-time 3D polygon game engine with arbitrary camera freedom, lightmaps, and internet multiplayer: **Quake**.

In 1995, Carmack recruited Abrash from Microsoft to id Software specifically to solve the unsolved problem of fast, software-rendered 3D graphics on standard Pentium/486 PCs without specialized 3D hardware accelerators.

---

## Chapter Guide & Key Architectural Inventions

| Chapter | Title | Key Architectural Concepts & Carmack Breakthroughs |
| :--- | :--- | :--- |
| [Chapter 60](chapter-60.md) | **Compiling BSP Trees** | The backstory of Carmack recruiting Abrash to id Software in 1995; taking 3D BSP trees from mathematical concept into a production compiler (`qbsp`). |
| [Chapter 61](chapter-61.md) | **Frames of Reference** | The mathematical foundations of 3D rotations, view coordinate systems, transformation matrices, and fixed-point optimizations. |
| [Chapter 62](chapter-62.md) | **One By One, Word By Word** | High-speed assembly polygon rasterization on x86 processors, sub-pixel accuracy, and eliminating cracks between polygons. |
| [Chapter 63](chapter-63.md) | **A Spreading Sickness** | Visible Surface Determination (VSD); analyzing z-buffers, painter's algorithms, and why standard real-time depth sorting failed for complex indoor scenes. |
| [Chapter 64](chapter-64.md) | **Quake's Visible-Surface Determination: The PVS and the BSP** | **Carmack's PVS Breakthrough**: Pre-computing the **Potentially Visible Set** for every convex leaf in the 3D BSP tree during map compilation, drastically pruning the polygons submitted to the rasterizer. |
| [Chapter 65](chapter-65.md) | **3-D Clipping and Other Thoughts** | Near clip planes, homogeneous clip space, avoiding frustum artifacts, and view-frustum polygon slicing. |
| [Chapter 66](chapter-66.md) | **Quake's 3-D Engine: The Big Picture** | Complete architectural walkthrough of the Quake rendering pipeline: world model, alias models (monsters/players), particles, and dynamic entities. |
| [Chapter 67](chapter-67.md) | **Sorted Spans in Action** | The debate between independent 1/z span sorting and front-to-back BSP span sorting; benchmarking fill-rate and memory overhead. |
| [Chapter 68](chapter-68.md) | **Quake's Lighting Model** | **Carmack's Surface Caching Discovery**: Separating high-frequency surface texture mapping from low-frequency static lightmaps, and the mathematical derivation of lighting polygons without floating-point division per pixel. |
| [Chapter 69](chapter-69.md) | **Surface Caching: Quake's Hidden Treasure** | The implementation details of the Surface Cache: dynamically rasterizing lit, mipmapped surfaces into RAM and caching them across frames to achieve blisteringly fast texture mapping. |
| [Chapter 70](chapter-70.md) | **Quake: A Post-Mortem and a Glimpse into the Future** | Retrospective on the Quake development cycle, what worked, architectural compromises, and the inevitable shift toward hardware 3D accelerators. |

---

## Source & License
Source: [jagregory/abrash-black-book](https://github.com/jagregory/abrash-black-book) under the original Coriolis Group open publishing license.
