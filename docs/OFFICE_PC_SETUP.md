# Office PC setup — from zero

Turns a spare Windows PC into the always-on tender searcher. It reads the bank/NGO sites that refuse GitHub
(Janata Bank, Islami Bank, WaterAid, Nutrition International) every 10 minutes, saves the results to the same
database as the dashboard, and GitHub warns you by Telegram/email if the PC stops.

Time: about 45 minutes, once. You need: the spare PC, internet, a USB stick, and the main PC (the one with
`F:\Tender Agent`).

---

## Part A — Prepare Windows (spare PC)

1. **Update Windows**: Start → Settings → Windows Update → *Check for updates*. Install everything, restart, repeat
   until nothing is left.
2. **Give your Windows account a password** (needed so the job runs after a restart without anyone signing in):
   Settings → Accounts → Sign-in options → Password → Add/Change. Remember it.
3. **Never sleep**: Settings → System → Power (& battery) → *Screen and sleep* → set **"put my device to sleep"**
   to **Never** (both "plugged in" options if shown). Screen turning off is fine.
4. **Restart after power cuts** (recommended): restart the PC, press the BIOS key while it starts (usually `Del`,
   `F2` or `F10`), find **"Restore on AC power loss"** / **"After power failure"** → **Power On**. Save and exit.
   If you cannot find it, skip this step (then switch the PC on yourself after a power cut).
5. Keep it on the office internet (cable is better than Wi-Fi).

## Part B — Install the programs (spare PC)

6. **Python**: open <https://www.python.org/downloads/windows/>, download the latest **Python 3.12 or 3.13
   "Windows installer (64-bit)"**, run it. On the first screen **tick "Add python.exe to PATH"**, then
   *Install Now*.
7. **Git**: open <https://git-scm.com/download/win>, download **64-bit Git for Windows Setup**, run it and keep
   clicking *Next* (the defaults are fine).
8. **Check both**: press Start, type `PowerShell`, open **Windows PowerShell**, and run:
   ```
   python --version
   git --version
   ```
   Both must print a version number. If one says "not recognized", close PowerShell, open it again; if it still
   fails, re-run that installer.

## Part C — Download the agent (spare PC, PowerShell)

9. Run these one by one (each can take a few minutes):
   ```
   cd C:\
   git clone https://github.com/saki3-ca/tender-agent.git
   cd C:\tender-agent
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
   The agent is now in `C:\tender-agent`. (This guide is in `C:\tender-agent\docs\OFFICE_PC_SETUP.md`.)

## Part D — Copy the secret settings file (.env)

10. On the **main PC**, copy `F:\Tender Agent\.env` to the USB stick.
    *(If you can't see it: File Explorer → View → Show → File name extensions + Hidden items.)*
11. On the **spare PC**, copy it from the USB stick into `C:\tender-agent\` so the file is
    `C:\tender-agent\.env`. **Then delete it from the USB stick.** Never email or WhatsApp this file: it holds the
    database master key.
12. Test the connection (spare PC, PowerShell, in `C:\tender-agent`):
    ```
    python run_monitor.py --office-pc
    ```
    After about a minute it prints a summary. You want **`sources_ok 4`** and **`sources_failed 0`**.

## Part E — Start the automatic job

13. Still in `C:\tender-agent`, run:
    ```
    powershell -ExecutionPolicy Bypass -File scripts\install_office_pc_task.ps1
    ```
    A window asks for your **Windows password** (from step 2) — type it and press OK. It installs the job
    *"ACNABIN Tender Monitor (office PC)"*, which runs every 10 minutes, even after a restart with nobody signed in.

    *Optional — the whole agent on this PC instead of only the 4 GitHub-blocked sites:*
    `powershell -ExecutionPolicy Bypass -File scripts\install_office_pc_task.ps1 -Full -IntervalMinutes 30`
    (every 30 minutes is safer than 10 for the full list: some sites block an office that visits too often).

14. **Check it is working** (after ~15 minutes):
    ```
    python scripts\pc_status.py
    ```
    It must say **`Office PC: RUNNING NORMALLY`**. Details of each run: `C:\tender-agent\data\office_pc.log`.
    You can run the same `pc_status.py` command on the main PC at any time.

From now on: if the PC stops for 30+ minutes, the hourly GitHub run sends **one** Telegram message and email
("Office PC stopped"). Code changed on the main PC and pushed to GitHub reaches this PC automatically (it runs
`git pull` before every search).

---

## Part F — Let Claude (on the main PC) control this PC (SSH)

15. **Turn on the SSH server** — spare PC: Start → type `PowerShell` → right-click → **Run as administrator**:
    ```
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
    Start-Service sshd
    Set-Service sshd -StartupType Automatic
    whoami
    ipconfig
    ```
    Write down: the **user name** from `whoami` (the part after `\`), and the **IPv4 Address** from `ipconfig`
    (looks like `192.168.x.x`).
16. **Same office network?** Give those two values to Claude on the main PC; it sets up a key so it can connect
    without a password (you type the spare PC's password once while it does that).
17. **Different networks** (e.g. the spare PC is at home): install **Tailscale** (<https://tailscale.com/download>)
    on **both** PCs and sign in with the **same** account. In the Tailscale app on the spare PC, copy its
    address (`100.x.x.x`) and give Claude that instead of the `192.168` address. Do **not** open SSH to the
    internet through the router.

## Part G — See the screen from your phone (optional)

18. On the spare PC open <https://remotedesktop.google.com/access> in Chrome, sign in with your Google account,
    click *Set up remote access*, install, choose a PIN. On your phone install **Chrome Remote Desktop** and sign
    in with the same Google account: you can see and use the spare PC from anywhere.

---

## If something goes wrong

| Problem | Fix |
|---|---|
| `python` / `git` "not recognized" | Close and reopen PowerShell. Still failing: re-run the installer (Python: tick *Add to PATH*). |
| `pip install` fails | Check internet; run `python -m pip install --upgrade pip` and try again. |
| Step 12 says no database connection | The `.env` file is missing or in the wrong folder — it must be `C:\tender-agent\.env`. |
| Installer: "The user name or password is incorrect" | Use the Windows password from step 2 (not a PIN). |
| `pc_status.py` says NOT RUNNING | PC asleep/off/offline? Open *Task Scheduler* → *ACNABIN Tender Monitor (office PC)* → *Last Run Result*; read `data\office_pc.log`. |
| Remove everything | PowerShell (admin): `Get-ScheduledTask -TaskName "ACNABIN*" \| Unregister-ScheduledTask -Confirm:$false`, then delete `C:\tender-agent`. |
