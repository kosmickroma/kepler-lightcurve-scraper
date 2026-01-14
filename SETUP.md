# Complete Setup Guide
## Windows WSL2 + Linux/macOS Installation

This guide walks you through setting up the Kepler Light Curve Scraper from scratch. Follow the instructions for your operating system.

---

## Table of Contents

- [Windows (WSL2 - RECOMMENDED)](#windows-wsl2---recommended)
- [Linux](#linux-ubuntu--debian)
- [macOS](#macos)
- [Troubleshooting](#troubleshooting)

---

## Windows (WSL2 - RECOMMENDED)

**Why WSL?** Testing revealed Windows has lightkurve cache corruption issues causing 60% failure rates. WSL2 (Windows Subsystem for Linux) provides Linux stability while staying on Windows.

### Step 1: Install WSL2 (10 minutes)

**Open PowerShell as Administrator** and run:

```powershell
wsl --install
```

This installs:
- WSL2 (Windows Subsystem for Linux)
- Ubuntu (default Linux distribution)
- All necessary components

**Reboot your computer** when prompted.

### Step 2: Set Up Ubuntu (5 minutes)

After reboot, Ubuntu will launch automatically:

1. **Create a username** (lowercase, no spaces)
   ```
   Enter new UNIX username: yourname
   ```

2. **Create a password** (you won't see it as you type - this is normal)
   ```
   New password: [type password]
   Retype new password: [type password]
   ```

3. **Update Ubuntu packages:**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

### Step 3: Install Python 3.10+ (5 minutes)

```bash
# Check Python version (should be 3.10+)
python3 --version

# If version is too old, install Python 3.11
sudo apt install python3.11 python3.11-venv python3-pip -y

# Create alias (optional but convenient)
echo "alias python=python3" >> ~/.bashrc
source ~/.bashrc
```

### Step 4: Navigate to Your Windows Files

Your Windows C: drive is mounted at `/mnt/c/`:

```bash
# Navigate to your project location
cd /mnt/c/Users/YourUsername/

# Example: cd /mnt/c/Users/carol/
```

**Tip:** Use tab completion! Type `cd /mnt/c/Users/ca` and hit TAB.

### Step 5: Clone/Copy the Scraper

**Option A: Clone from GitHub (if you've uploaded it)**
```bash
git clone https://github.com/yourusername/kepler-lightcurve-scraper.git
cd kepler-lightcurve-scraper
```

**Option B: If you already have the folder**
```bash
# Navigate to where you extracted it
cd /mnt/c/Users/YourUsername/kepler-lightcurve-scraper
```

### Step 6: Create Virtual Environment (2 minutes)

```bash
# Create virtual environment
python3 -m venv venv_linux

# Activate it
source venv_linux/bin/activate

# Your prompt should now show (venv_linux)
```

**Important:** Always activate this environment before running the scraper!

### Step 7: Install Dependencies (5-10 minutes)

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs:
- lightkurve (Kepler data access)
- astropy (astronomy utilities)
- numpy, pandas, scipy (data processing)
- psutil (memory monitoring)
- ~35 packages total

**Grab coffee, this takes a few minutes.** ☕

### Step 8: Verify Installation (3 minutes)

```bash
python scripts/test_conservative.py
```

**Expected output:**
```
✓ 100% success rate (5/5 targets)
✓ Peak memory <4GB
✓ No timeout errors
✓ Bottleneck identified

🎉 TEST PASSED - Architecture is stable and ready for scaling
```

**If this passes, you're done!** 🎉

### Step 9: Running Long Sessions (Optional)

For runs that take hours/days, use `screen` to keep them alive even if you close the terminal:

```bash
# Install screen
sudo apt install screen -y

# Start a named screen session
screen -S kepler_scraper

# Run your scraper
python scripts/xenoscan_scraper.py --targets 150000 --workers 4

# Detach from screen: Press Ctrl+A, then D

# Close WSL terminal - your scraper keeps running!

# Later, reattach to see progress:
screen -r kepler_scraper
```

---

## Linux (Ubuntu / Debian)

### Prerequisites

```bash
sudo apt update
sudo apt install python3.10 python3.10-venv python3-pip git -y
```

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/kepler-lightcurve-scraper.git
cd kepler-lightcurve-scraper

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Test installation
python scripts/test_conservative.py
```

---

## macOS

### Prerequisites

**Install Homebrew** (if not already installed):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**Install Python 3.10+:**
```bash
brew install python@3.10
```

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/kepler-lightcurve-scraper.git
cd kepler-lightcurve-scraper

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Test installation
python scripts/test_conservative.py
```

---

## Troubleshooting

### "python3: command not found"

**Fix:**
```bash
# Ubuntu/Debian
sudo apt install python3 -y

# macOS
brew install python@3.10
```

### "pip: command not found"

**Fix:**
```bash
# Ubuntu/Debian
sudo apt install python3-pip -y

# macOS
python3 -m ensurepip --upgrade
```

### "ModuleNotFoundError: No module named 'psutil'"

You forgot to activate the virtual environment!

**Fix:**
```bash
source venv_linux/bin/activate  # WSL/Linux
# OR
source venv/bin/activate  # macOS

# Then install again
pip install -r requirements.txt
```

### "Could not resolve KIC XXXXXX to a sky position"

The target doesn't exist in the Kepler catalog. This is expected for some IDs.

**Fix:** The scraper will retry 3 times, then skip gracefully. This is normal behavior.

### "I/O operation on closed file" during downloads

This is a known lightkurve quirk on some quarters. The scraper handles it gracefully and continues with remaining quarters.

**Normal behavior:** You'll see warnings like:
```
Quarter 16/18 failed: I/O operation on closed file
Successfully downloaded 16/18 quarters
```

This is fine! You got 16 out of 18 quarters. Science proceeds.

### Cache Corruption Errors

If you see errors about truncated/corrupt cache files:

**Fix:**
```bash
python scripts/clear_cache.py
```

This clears lightkurve's cache and forces fresh downloads.

### Memory Issues / OOM Kills

If the scraper gets killed without error messages, you ran out of RAM.

**Fix:**
1. Reduce workers: `--workers 2` (instead of 4 or 6)
2. Monitor memory: `watch -n 1 free -h` (in another terminal)
3. Close other applications

### WSL Can't Find Windows Files

Your Windows C: drive is at `/mnt/c/`, not `C:\`

**Example:**
- Windows: `C:\Users\carol\kepler-lightcurve-scraper`
- WSL: `/mnt/c/Users/carol/kepler-lightcurve-scraper`

### Permission Denied Errors

**Fix:**
```bash
# Make scripts executable
chmod +x scripts/*.py
```

---

## Environment Management

### Activating the Environment

**ALWAYS activate before running the scraper:**

```bash
# WSL/Linux
source venv_linux/bin/activate

# macOS/Linux
source venv/bin/activate

# You should see (venv_linux) or (venv) in your prompt
```

### Deactivating

```bash
deactivate
```

### Checking What's Installed

```bash
pip list
```

### Updating Dependencies

```bash
pip install --upgrade -r requirements.txt
```

---

## Performance Tuning

### Checking System Resources

```bash
# Memory available
free -h

# CPU cores
nproc

# Disk space
df -h
```

### Recommended Worker Counts

| RAM Available | Recommended Workers | Max Workers |
|---------------|---------------------|-------------|
| 4GB | 2 | 3 |
| 8GB | 4 | 6 |
| 16GB | 6 | 10 |
| 32GB+ | 8 | 15 |

**Start conservative, scale gradually.**

---

## Data Management

### Where Files Go

```
kepler-lightcurve-scraper/
├── data/
│   └── raw/           # FITS files (can be large!)
├── checkpoints/       # Resume state (keep these!)
└── download_results.csv  # Success log
```

### Disk Space Management

FITS files can be large. After processing 150K targets, you'll have ~50-80GB of data.

**Options:**
1. **Keep FITS files:** For re-analysis, archive
2. **Delete after feature extraction:** In Phase 2, we extract features and delete FITS to save space

### Backing Up Checkpoints

```bash
# Copy checkpoint to safe location
cp checkpoints/scraper_checkpoint.json ~/backup_checkpoint.json

# Restore if needed
cp ~/backup_checkpoint.json checkpoints/scraper_checkpoint.json
```

---

## Next Steps

✅ Setup complete? Run the validation test:

```bash
python scripts/test_conservative.py
```

✅ Test passed? Try a small batch:

```bash
python scripts/xenoscan_scraper.py --targets 100 --workers 2
```

✅ Ready for production? See [README.md](README.md) for full usage guide.

---

**Need help?** Open an issue on GitHub or check the Discussions tab. We're here to help!

**Last Updated:** 2026-01-13 | **Version:** 1.0.0
