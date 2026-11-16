# ForceProject / Application with Web Backend and Front View

A web-based industrial safety and simulation platform built with Python, FastAPI, and NiceGUI. The project combines user authentication, sensor monitoring, toxic-gas management, accident-case education, file browsing, and atmospheric-dispersion simulation workflows into a unified web application.

The repository is currently in a closed / archived state and is maintained as a reference implementation and local research/demo project rather than an active production deployment.

## Overview

This project provides a browser-based front end for operational monitoring and safety analysis. It is centered around a NiceGUI application with a FastAPI backend and supports interactive pages for:

- user login and role-based access control
- real-time or periodic sensor data viewing
- toxic-gas database administration
- accident education and case browsing
- FDS and HYSPLIT simulation workflows
- map-based visualization and room/simulation display interfaces

The application structure is modular, with separate packages for authentication, sensors, gas exploration, simulation, and UI components.

## Core features

- Role-based access control (RBAC)
  - users, roles, and permissions are managed in the auth subsystem
  - protected routes are enforced with middleware and session handling

- Sensor monitoring dashboard
  - sensor metadata, latest readings, and online/offline states
  - refresh logic and status presentation for monitoring data

- Gas database management
  - toxic-gas catalog and chemical database
  - CRUD operations, search/filter capabilities, and export support

- Case browsing and document review
  - directory-based browsing of case data
  - image, text, PDF, and media preview support
  - case metadata and file access workflows

- Simulation tools
  - FDS-based dispersion and scenario simulation
  - HYSPLIT and related atmospheric simulation workflows
  - session-based result history and visualization

- Map and 3D presentation
  - interactive map pages
  - room view and simulation overlays
  - 3D rendering for FDS-style simulation outputs

## Tech stack

- Front end: NiceGUI
- Backend: FastAPI + Uvicorn
- Data layer: SQLite, SQLAlchemy, Pandas
- UI style: NiceGUI / Quasar-style component-based interface
- Visualization: Plotly, Matplotlib, Pillow, image overlays
- Scientific / data utilities: NumPy, SciPy, OmegaConf

## Project structure

```text
GasExplosion/
├── conf/                       # Application configuration files
├── data/                      # Case data, accident data, and supporting datasets
├── db/                        # SQLite databases created at runtime
├── doc/                       # User manuals and project notes
├── fds/                       # FDS simulation inputs and processing
├── fds3d/                     # 3D FDS rendering / simulation support
├── hysplit/                   # HYSPLIT simulation code
├── hysplitBackward/           # Backward trajectory simulation support
├── hysplitGaussian/           # Gaussian plume visualization support
├── log/                       # Runtime logs
├── python/                    # Main application modules
│   ├── auth/                 # Authentication and RBAC
│   ├── components/           # Shared UI components and layouts
│   ├── explorer/             # Gas and chemistry exploration
│   ├── sensors/              # Sensor reader/writer and UI
│   ├── util/                 # Shared utilities
│   ├── main.py               # Main application entry point
│   ├── init_auth_db.py       # Initializes auth database
│   ├── init_gas_db.py        # Initializes gas database
│   ├── init_sensors_db.py    # Initializes sensor database
│   └── ...
├── static/                    # Static web assets
├── .gitignore
├── requirements.txt
├── serve-forever.ps1         # Windows startup helper
├── clear-fds-simulations.ps1
├── init-auth-db.ps1
├── init-chemical-db.ps1
├── init-gas-db.ps1
├── init-sensors-db.ps1
├── readme.md
├── todolist.md
└── ...
```

## Runtime and environment

### Supported platforms

- Windows 11 / Windows 10 (primary target)
- Linux-based environments may also work with the same Python stack

### Python version

- Python 3.11 recommended
- Anaconda / Miniconda is recommended for local setup

### Dependency installation

From the project root:

```powershell
conda create -n gasexplosion python=3.11
conda activate gasexplosion
pip install -r requirements.txt
```

The project also includes a Python-specific requirements file:

```powershell
pip install -r python\requirements.txt
```

## Initializing the application

The project creates and initializes local database files on first run. Typical initialization steps include:

```powershell
python python\init_auth_db.py
python python\init_gas_db.py
python python\init_sensors_db.py
```

There are also helper scripts in the repo root for environment setup and routine maintenance.

## Starting the app

From the repository root:

```powershell
python python\main.py
```

Or use the included Windows launcher:

```powershell
.\serve-forever.ps1
```

The application defaults to a local web address similar to:

```text
http://127.0.0.1:8000
```

## Default access and demo accounts

The application creates sample accounts on first launch. Examples include:

- username: testuser
  password: password123
- username: guest
  password: guest123

These are useful for testing auth flows and role-based restrictions.

## Main routes

The application exposes multiple functional pages and endpoints, including:

- `/` - landing page
- `/login` - login page
- `/accidents` - accident education / case information
- `/caseBrowser` - case file browser
- `/gasExplorer` - gas database management
- `/sensors` - sensor monitoring
- `/privilege` - role and user management
- `/simulationFDS` - FDS simulation interface
- `/simulationHysplit` - HYSPLIT simulation interface
- `/map` and `/room` - map / scene presentation pages

## Configuration

The application uses YAML configuration files under the `conf/` directory. Key configuration is defined in files such as:

- `conf/project.yml`
- `conf/simulation.yml`
- `conf/permission.yml`
- `conf/fds3d_obst_color.yml`

These files control project metadata, permissions, and simulation settings.

## Project documentation

The repository includes supporting documents under `doc/`:

- `doc/软件安装使用说明书.md` - installation and setup guide
- `doc/软件操作指南.md` - operational usage guide
- `doc/搭建仿真动态显示系统说明书.md` - simulation display system documentation
- `doc/authentication.md` - authentication notes

## Current status

This project is currently closed for now. It is not intended as an active public deployment or maintained production service at this stage. The codebase remains valuable as a demonstration of a full-stack safety dashboard and simulation research platform.

## Notes

- The project is heavily oriented toward academic / research-style industrial safety analysis.
- Several modules and data assets are environment-specific and may need to be adjusted for a different machine or deployment context.
- Simulation workflows depend on external data and local file structures; they should be treated as project-specific rather than generic library code.

## License

No explicit OSS license file is present in the repository at this time. The project should therefore be used with caution and according to the repository owner’s local policy unless a separate license statement is supplied.
