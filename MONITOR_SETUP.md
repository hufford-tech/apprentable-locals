# Setting up the daily monitor (Windows Task Scheduler)

`monitor.py` checks every local's `application_url` for changes using plain
HTTP requests -- no paid API calls. It should run once a day so that, over
time, `out/monitor_state.json` builds up a real history of which pages
change and how often. `run_monitor.bat` is the file you'll schedule; it runs
the check and appends a timestamped entry to `out/monitor_log.txt`.

You do not need to have used Task Scheduler before. Follow these steps in
order.

## 1. Open Task Scheduler

Press the Windows key, type `Task Scheduler`, and press Enter.

## 2. Create a new task

In the right-hand panel, click **Create Task...** (not "Create Basic Task" --
the full dialog gives you more control and is not any harder to use).

## 3. Fill in the "General" tab

- **Name:** `IBEW Apprenticeship Monitor`
- **Description:** `Daily check of apprenticeship application pages for content changes.`
- Select **Run whether user is logged on or not**.
- Check **Run with highest privileges** if it's available (not required, but
  avoids permission prompts).

## 4. Set the schedule -- "Triggers" tab

- Click **New...**
- **Begin the task:** On a schedule
- **Settings:** Daily
- **Start:** pick tomorrow's date, and set the time to **6:00:00 AM**
- Leave **Recur every 1 days**
- Click **OK**

## 5. Set what it runs -- "Actions" tab

- Click **New...**
- **Action:** Start a program
- **Program/script:** click **Browse...** and select this file:
  `C:\Users\andre\ibew\run_monitor.bat`
- Leave **Add arguments** and **Start in** blank -- the batch file sets its
  own working directory.
- Click **OK**

## 6. Leave "Conditions" and "Settings" tabs at their defaults

The defaults are fine for this task. One exception: on the **Conditions**
tab, if this machine is a laptop that's sometimes on battery, you may want
to uncheck **Start the task only if the computer is on AC power** so a
missed morning doesn't skip the check entirely.

## 7. Save it

Click **OK** at the bottom of the dialog. Windows will ask for your account
password to allow the task to run whether you're logged in or not -- enter
it and click OK.

## 8. Test it once by hand

Right-click the new task in the list and choose **Run**. Then open
`out\monitor_log.txt` and confirm a new entry appeared with today's date and
`exit code 0` at the end. If you see anything else, check `out\monitor_log.txt`
for the Python traceback -- it will be appended just like normal output.

## What this builds toward

Right now `out/monitor_freshness.csv` (`monitor_days_since_change` /
`consecutive_failures` per local) is not fed into `compute_status.py` at
all -- there isn't enough history yet for it to mean anything. A single
snapshot can't tell you whether a page changes weekly or never. Once this
task has run daily for three to four weeks, `monitor_days_since_change`
becomes a real, trustworthy signal, and at that point it's the correct
input to wire into `is_stale` (which is empty for every record today, by
design, for exactly this reason). Don't wire it in before then -- an
`is_stale` computed from one or two data points would be noise dressed up
as signal.

## If something goes wrong

- **The task shows "Last Run Result" other than `(0x0)`:** open
  `out\monitor_log.txt`, find the most recent `====` header, and read the
  lines under it -- monitor.py prints its own errors there.
- **`out\monitor_state.json` isn't updating:** confirm `run_monitor.bat` was
  pointed at the actual file path above, not a copy, and that the "Start in"
  field was left blank (the batch file `cd`s to its own folder first).
- **You want to stop it:** open Task Scheduler, find
  `IBEW Apprenticeship Monitor` in the list, right-click, and choose
  **Disable** (or **Delete** to remove it entirely).
