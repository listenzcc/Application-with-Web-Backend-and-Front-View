# Application with Web Backend and Front View

---

[toc]

## Abstract

The project runs [NiceGUI](https://nicegui.io/).
The NiceGUI seems to be using [FastAPI](https://fastapi.tiangolo.com/) for backend and [TailwindCSS](https://tailwindcss.com/) for style.
And the front end can be either web browser or other similar applications.

Documents: [PlantUML](https://plantuml.com/guide)

## Dev diary

- 20251202
  - Initialize the repository, ignore rules, configuration, and README.

- 20251203
  - Add the initial authentication features, shared layout components, and test page.

- 20251205
  - Implement authentication, user roles and permissions, application logging, and database initialization.

- 20251206
  - Add user session management and authentication middleware.

- 20251207
  - Add navigation for gas and case exploration, file browsing, and the first simulation page with map integration.
  - Implement the toxic-gas database and improve case browsing.

- 20251208
  - Refactor the application structure and add sensor database initialization, data access, and display features.

- 20251209
  - Add sensor deletion and a latest-reading API; improve sensor status colors and refresh readings every second.

- 20251210
  - Add PowerShell startup scripts and YAML configuration, and make the application feel more like a desktop app.
  - Adjust map geometry and add a favicon.

- 20251211
  - Add click-through interaction on the map.

- 20251217
  - Add window-mode switching to the application entry point.

- 20251218
  - Add FDS simulation scripts and implement the initial FDS simulation workflow.

- 20251221
  - Add safety-threshold fields to the toxic-gas database and its management UI.
  - Improve the accident-education interface and responsive layout.

- 20251226
  - Display simulation overlays and imagery on the map; track simulation sessions in the FDS workflow.

- 20251227
  - Improve FDS page layout and sensor-data handling, and update map overlays when simulation data changes.

- 20251231
  - Apply a cross-project functionality and performance improvement pass.

- 20260126
  - Add weather-data configuration and resolve weather paths dynamically.
  - Add the FDS simulation page and navigation; improve session IDs and show simulation progress.

- 20260127
  - Refactor simulation configuration and session management for FDS and HYSPLIT; remove unused simulation and grid-generation code.

- 20260312
  - Add an initial FDS simulation-result analysis tool.

- 20260313
  - Add the project to-do list and move sensitive configuration out of the public static asset area.

- 20260316
  - Improve case-browser styling and file handling.

- 20260317
  - Refine case-browser cover-image sizing and enable the persistent server script to activate the Conda environment.

- 20260318
  - Fix online-status reporting for sensors without readings.

- 20260322
  - Add installation and operation manuals.

- 20260323
  - Make case images full-width and place the case abstract below the image.

- 20260324
  - Add cases 案例一、二、三 and support case videos.

- 20260420
  - Update simulation configuration and UI labels, and add a HYSPLIT analysis script.

- 20260711
  - Add the project Python dependency list.

- 20260911
  - Add chemical exploration and initialize the chemical and gas databases with sample data.
  - Add an FDS input parser and update the room image.
  - Improve HYSPLIT map controls and HUD, including hazard-contour visualization.

- 20260915
  - Improve 3D plume rendering, fill internal grid holes, and add OrbitControls.

- 20260916
  - Improve 3D camera controls and rendering stability.
  - Add Gaussian HYSPLIT visualization and interactive backward-tracking visualization with contours.

- 20260921
  - Add direct input editing and DEVC visualization to the FDS 3D interface.
  - Apply a consistent dark theme across layouts and HTML pages.

- 20261012
  - Refine the 3D FDS template to improve simulation accuracy and detail.

- 20261013
  - Replace the outdated 3D FDS template with a large-domain CO-dispersion template.
  - Improve simulation data presentation and add accident statistics for casualties and gas composition.

- 20261016
  - Add configurable OBST coloring and rendering to the 3D simulation.
  - Refine simulation-page layouts, enlarge the header text, and clarify FDS labels.

- 20261020
  - Add monitoring data and station configurations for Wuwei and Zhangye.
