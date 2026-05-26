# Installation Instructions

> **Warning:** This app is still a work in progress and may contain errors. Use results for informational purposes only and verify any financial figures independently.

## Prerequisites

### 1. Python 3.10 or higher
Download and install Python from [https://www.python.org/downloads/](https://www.python.org/downloads/).

During installation on Windows, check **"Add Python to PATH"** before clicking Install.

Verify the installation:
```
python --version
```

### 2. Git
Download and install Git from [https://git-scm.com/downloads](https://git-scm.com/downloads).

Verify the installation:
```
git --version
```

---

## Installation Steps

### 1. Clone the repository

Navigate to whichever folder you'd like the app to live inside — it can be anywhere on your computer (Documents, Desktop, a projects folder, etc.). Cloning will automatically create a `retirementplanner` subfolder there, so you don't need to create one yourself.

**Windows:**
```
cd C:\Users\YourName\Documents
```

**Mac/Linux:**
```
cd ~/Documents
```

Then clone the repository:
```
git clone https://github.com/mcleanjx/retirementplanner.git
cd retirementplanner
```

### 2. (Optional) Create a virtual environment
A virtual environment keeps the app's dependencies isolated from other Python projects. If this is the only Python app you're running, you can skip this step.

**Windows:**
```
python -m venv venv
venv\Scripts\activate
```

**Mac/Linux:**
```
python -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```
pip install -r requirements.txt
```

This installs the following packages:

| Package | Version | Purpose |
|---------|---------|---------|
| streamlit | ≥ 1.35.0 | Web app framework |
| plotly | ≥ 5.22.0 | Interactive charts |
| pandas | ≥ 2.2.0 | Data processing |
| numpy | ≥ 1.26.0 | Numerical calculations |

---

## Running the App

Before running the app, you must be in the project folder. Open a terminal and navigate there:

**Windows:**
```
cd C:\path\to\retirementplanner
```

**Mac/Linux:**
```
cd ~/path/to/retirementplanner
```

Then run:
```
streamlit run app.py
```

The app will open automatically in your default browser at `http://localhost:8501`.

### Creating a Shortcut (Windows)

Instead of opening a terminal every time, you can create a double-click shortcut:

1. Open Notepad and paste the following, replacing the path with your actual project folder location:
   ```
   @echo off
   cd /d "C:\path\to\retirementplanner"
   streamlit run app.py
   pause
   ```
2. Save the file as `run_app.bat` (make sure Notepad doesn't add `.txt` — choose "All Files" in the save dialog)
3. Double-click `run_app.bat` to launch the app

> If you used a virtual environment, add `call venv\Scripts\activate` on the line before `streamlit run app.py`.

---

## Updating to the Latest Version

```
git pull origin main
pip install -r requirements.txt
```

---

## Troubleshooting

**`python` not recognized** — Try `python3` instead, or re-install Python with "Add to PATH" checked.

**`pip` not recognized** — Try `python -m pip install -r requirements.txt`.

**Port already in use** — Run on a different port: `streamlit run app.py --server.port 8502`

**Virtual environment not activating on Windows** — Run PowerShell as Administrator and execute: `Set-ExecutionPolicy RemoteSigned`
