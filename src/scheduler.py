import time
import logging
from datetime import datetime
import pytz
import subprocess
import sys
from pathlib import Path

from config.settings import TIMEZONE

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("src.scheduler")

class LocalScheduler:
    """
    Python-based local scheduler fallback.
    Can be used to orchestrate collection runs without Slurm/scrontab.
    """
    def __init__(self, check_interval_sec: int = 30):
        self.check_interval_sec = check_interval_sec
        # Target schedules: (day_of_week_ints, hour, minute)
        # Weekdays: Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4
        # Saturday=5, Sunday=6
        self.schedules = [
            # Weekdays
            (list(range(5)), 7, 30),
            (list(range(5)), 12, 30),
            (list(range(5)), 18, 0),
            # Saturdays
            ([5], 10, 0),
            ([5], 16, 0),
            # Sundays
            ([6], 14, 0)
        ]
        self.last_run_date = None
        self.last_run_time_slot = None

    def _should_trigger(self, now: datetime) -> bool:
        """
        Determines if a collection script should be triggered at the current minute.
        Prevents multiple triggers in the same minute.
        """
        current_day = now.weekday()
        current_hour = now.hour
        current_minute = now.minute

        for days, hr, mt in self.schedules:
            if current_day in days and current_hour == hr and current_minute == mt:
                slot_id = f"{current_day}_{hr}_{mt}"
                date_str = now.date().isoformat()
                
                # Check if we already ran in this slot today
                if self.last_run_date == date_str and self.last_run_time_slot == slot_id:
                    return False
                
                self.last_run_date = date_str
                self.last_run_time_slot = slot_id
                return True
        return False

    def trigger_collection(self):
        """Launches the collector matrix snapshot process in a subprocess."""
        project_root = Path(__file__).resolve().parent.parent
        script_path = project_root / "run_collector.py"
        
        logger.info(f"Triggering log collection run via {script_path}")
        try:
            # Run using the current python executable
            result = subprocess.run(
                [sys.executable, str(script_path), "--action", "matrix"],
                check=True,
                capture_output=True,
                text=True
            )
            logger.info("Collection process output:")
            logger.info(result.stdout)
        except subprocess.CalledProcessError as e:
            logger.error(f"Collection process failed with exit code {e.returncode}")
            logger.error(e.stderr)

    def start(self):
        """Starts the scheduler daemon loop."""
        logger.info(f"Starting Local Scheduler daemon. Timezone: {TIMEZONE}")
        tz = pytz.timezone(TIMEZONE)
        
        # Log schedule
        logger.info("Registered schedules:")
        for days, hr, mt in self.schedules:
            day_label = "Weekdays" if days == list(range(5)) else f"Day(s) {days}"
            logger.info(f"  - {day_label} at {hr:02d}:{mt:02d}")

        try:
            while True:
                now = datetime.now(tz)
                if self._should_trigger(now):
                    logger.info(f"Scheduled time matched! Triggering run at local time: {now.isoformat()}")
                    self.trigger_collection()
                
                time.sleep(self.check_interval_sec)
        except KeyboardInterrupt:
            logger.info("Scheduler daemon stopped by user.")

if __name__ == "__main__":
    scheduler = LocalScheduler()
    scheduler.start()
