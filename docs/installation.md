# Installation

This guide covers how to install `evid` on your system using `uv`, the recommended tool for dependency management. For Windows users, we also provide instructions for setting up `evid` using Windows Subsystem for Linux (WSL2), which is recommended for a smoother experience with GUI and LaTeX features.

## Prerequisites

- **Python**: Version 3.11 or higher (but less than 4.0).
- **uv**: For dependency management and installation.
- **Git**: To clone the repository and enable optional Git-based version control for datasets.
- **Optional**: A LaTeX distribution (e.g., TeX Live) for generating LaTeX documents.
- **For WSL2 (Windows)**: A Linux distribution (e.g., Ubuntu) installed via WSL2, plus additional system dependencies for GUI support.

## Installation Options

Choose one of the following installation methods based on your operating system:

- [Standard Installation](#standard-installation) (Linux, macOS, or Windows with native Python)
- [WSL2 Installation](#wsl2-installation-for-windows) (Recommended for Windows users)

## Standard Installation

These steps work for Linux, macOS, or Windows (if using native Python without WSL2).

1. **Clone the Repository**

```bash
git clone <repository-url>
cd evid
```

2. **Install uv**

If you don't have `uv` installed, run:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Ensure `uv` is in your PATH. On Linux/macOS, you may need to add:

```bash
export PATH="$HOME/.cargo/bin:$PATH"
```

On Windows (without WSL2), `uv` is typically added to your PATH automatically, but you can verify by running `uv --version` in a Command Prompt.

3. **Install System Dependencies (Linux/macOS)**

For Linux, install the following dependencies to support the GUI and optional Git features:

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-dev qt6-base-dev libx11-xcb1 libxcb-cursor0 libegl1 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-xinput0 libfontconfig1 libgl1 libglu1-mesa libopengl0 libxcb-glx0
```

For macOS, use Homebrew to install Git:

```bash
brew install git
```

Note: Some Qt6 dependencies may require additional setup on macOS; consult the [PyQt6 documentation](https://www.riverbankcomputing.com/static/Docs/PyQt6/installation.html) if issues arise.

4. **Install Dependencies**

Use `uv` to install all required dependencies:

```bash
uv pip install .
```

This installs `evid` and dependencies like `PyQt6`, `pymupdf`, `pyyaml`, and `gitpython` (for optional Git support).

5. **Verify Installation**

Run the application to ensure it launches:

```bash
evid
```

This should open the `evid` GUI with a dark theme.

## WSL2 Installation for Windows

For Windows users, we recommend using Windows Subsystem for Linux (WSL2) to run `evid`. WSL2 provides a Linux environment that simplifies GUI and LaTeX support. These instructions are designed for beginners who have never used WSL2 before.

### Step 1: Set Up WSL2

1. **Enable WSL2**:
- Open the Windows Start menu, search for "Turn Windows features on or off," and open it.
- Scroll down, check the boxes for "Windows Subsystem for Linux" and "Virtual Machine Platform," then click OK.
- Restart your computer when prompted.

2. **Install a Linux Distribution**:
- Open the Microsoft Store app on Windows.
- Search for "Ubuntu" and install "Ubuntu 20.04 LTS" (or the latest version available).
- Launch Ubuntu from the Start menu. It will take a few minutes to set up, and you'll be asked to create a username and password (e.g., username: `user`, password: `yourpassword`). Remember these credentials.

3. **Update WSL2**:
- Open a Windows Command Prompt (search for "cmd" in the Start menu).
- Run the following command to ensure WSL2 is set as the default:
```cmd
wsl --set-default-version 2
```
- Verify the installation by running `wsl --list --verbose` in the Command Prompt. You should see Ubuntu listed with "2" as the version.

### Step 2: Install an X Server for GUI Support

To display the `evid` GUI in WSL2, you need an X server on Windows to handle Linux GUI applications.

1. **Install VcXsrv**:
- Download VcXsrv from [SourceForge](https://sourceforge.net/projects/vcxsrv/) (click the green "Download" button).
- Run the installer, choosing default options, and complete the installation.

2. **Configure VcXsrv**:
- Launch "XLaunch" from the Start menu (installed with VcXsrv).
- In the XLaunch wizard:
- Select "Multiple windows" and click Next.
- Select "Start no client" and click Next.
- Check "Disable access control" (important for WSL2) and click Next.
- Click Finish to start the X server. A small icon will appear in your system tray.
- Keep XLaunch running whenever you use `evid`'s GUI.

### Step 3: Install System Dependencies in Ubuntu

1. **Open Ubuntu**:
- Launch Ubuntu from the Start menu or run `wsl` in a Windows Command Prompt.

2. **Update Ubuntu**:
- Run the following commands to update the package lists and installed packages:
```bash
sudo apt update
sudo apt upgrade -y
```
- Enter your Ubuntu password when prompted.

3. **Install Required Dependencies**:
- Install the system dependencies needed for `PyQt6` and GUI functionality, plus Git for version control:
```bash
sudo apt install -y git python3 python3-pip python3-dev qt6-base-dev libx11-xcb1 libxcb-cursor0 libegl1 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-xinput0 libfontconfig1 libgl1 libglu1-mesa libopengl0 libxcb-glx0
```
- These packages ensure that the GUI and graphical components work correctly in WSL2.

4. **Optional: Install LaTeX**:
- To generate LaTeX documents (e.g., for labels and rebuttals), install TeX Live:
```bash
sudo apt install -y texlive-full
```
- Note: This is a large package (several GB), so you can skip it if you don't need LaTeX features.

### Step 4: Clone and Install evid

1. **Clone the Repository**:
- In the Ubuntu terminal, clone the `evid` repository:
```bash
git clone <repository-url>
cd evid
```

2. **Install uv**:
- Install `uv` in the Ubuntu environment:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
- Add `uv` to your PATH by adding this line to your `~/.bashrc`:
```bash
echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```
- Verify `uv` is installed by running:
```bash
uv --version
```

3. **Install Dependencies**:
- Install `evid` dependencies using `uv`:
```bash
uv pip install .
```

### Step 5: Configure GUI Display

1. **Set the DISPLAY Environment Variable**:
- In the Ubuntu terminal, add the following line to your `~/.bashrc` to configure the display for GUI applications:
```bash
echo 'export DISPLAY=$(ip route list default | awk "{print \$3}" | head -1):0' >> ~/.bashrc
source ~/.bashrc
```
- This sets the DISPLAY variable to point to your Windows X server.

### Step 6: Verify Installation

1. **Ensure XLaunch is Running**:
- Make sure XLaunch (VcXsrv) is running on Windows (check for the system tray icon).

2. **Run evid**:
- In the Ubuntu terminal, from the `evid` directory, run:
```bash
evid
```
- The `evid` GUI should appear on your Windows desktop with a dark theme.

### Troubleshooting WSL2

- **GUI Doesn't Appear**: Ensure XLaunch is running and the `DISPLAY` variable is set correctly. Try restarting XLaunch and running `export DISPLAY=:0` in the Ubuntu terminal.
- **Dependency Errors**: If `uv pip install` fails, ensure all system dependencies were installed (`qt6-base-dev`, `git`, etc.). Re-run `sudo apt install` for missing packages.
- **Slow Performance**: Ensure your WSL2 instance has enough memory (check via `wsl --list --verbose`). You can allocate more resources in a `.wslconfig` file (search online for WSL2 performance tuning).
- **LaTeX Issues**: If LaTeX documents fail to generate, verify that `texlive-full` is installed or install specific LaTeX packages as needed.

## Troubleshooting (General)

- **uv errors**: Ensure Python 3.11+ is installed and `uv` is correctly configured. Try `uv python use 3.11` if `uv` uses the wrong Python version.
- **Missing LaTeX**: If LaTeX documents fail to generate, install a LaTeX distribution like TeX Live (included in WSL2 instructions above).
- **GUI issues**: Verify that `PyQt6` is installed correctly. Check for Qt-related errors in the terminal output. For WSL2, ensure the X server is running.

For further help, check the [Development](development.md) section or file an issue on the repository.
